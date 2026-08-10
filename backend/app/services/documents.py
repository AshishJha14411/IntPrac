"""Resume and JD parsing.

Runs in a worker, never inline: parsing is asynchronous and the UI shows
``uploaded → parsing → ready | failed`` rather than blocking on it (FR-R3).

Extraction is heuristic and provenance-carrying. Every item records the source
span it came from (FR-R5), which is what lets a question cite the exact bullet
it is probing and lets a human see the extraction wasn't invented. Being able
to point at the line is worth more here than being clever about the parse.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domain.enums import DocumentStatus, ProfileItemKind, RequirementWeight
from app.models.content import Competency
from app.models.documents import (
    JDProfile,
    JDRequirement,
    JDVersion,
    ProfileItem,
    ResumeProfile,
    ResumeVersion,
)
from app.services import resume_quality, storage
from app.services.sanitize import detect_injection, normalise

logger = get_logger(__name__)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"(?<!\d)(\+?\d[\d\s().-]{7,}\d)(?!\d)")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_BULLET = re.compile(r"^\s*[-•*·‣▪]\s*")

def _clip(text: str, limit: int = 60) -> str:
    """Shorten to at most ``limit`` characters, never mid-word.

    Falls back to a hard slice only when the first word is itself longer than
    the limit, which is a URL or a mangled parse rather than a job title.
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[: limit + 1]
    cut = head.rfind(" ")
    return (head[:cut] if cut > 0 else text[:limit]).rstrip(" ,;:-")


_SECTION_HINTS: dict[ProfileItemKind, tuple[str, ...]] = {
    ProfileItemKind.SKILL: ("skills", "technologies", "tech stack", "toolkit"),
    ProfileItemKind.ROLE: ("experience", "employment", "work history", "professional"),
    ProfileItemKind.PROJECT: ("projects", "selected work", "portfolio"),
    ProfileItemKind.EDUCATION: ("education", "academic"),
    ProfileItemKind.CERTIFICATION: ("certification", "certificates", "licences", "licenses"),
}


@dataclass(slots=True)
class ExtractedItem:
    kind: ProfileItemKind
    payload: dict
    source_text: str
    span: tuple[int, int]
    prominence: int = 0


@dataclass(slots=True)
class ParsedResume:
    identity: dict = field(default_factory=dict)
    items: list[ExtractedItem] = field(default_factory=list)
    raw_text: str = ""


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------
def extract_text(content: bytes, content_type: str) -> str:
    if content_type == "application/pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if content_type.endswith("wordprocessingml.document"):
        import docx

        document = docx.Document(io.BytesIO(content))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    return content.decode("utf-8", errors="replace")


def _section_for(heading: str) -> ProfileItemKind | None:
    lowered = heading.lower()
    for kind, hints in _SECTION_HINTS.items():
        if any(hint in lowered for hint in hints):
            return kind
    return None


def parse_resume_text(text: str) -> ParsedResume:
    text = normalise(text)
    parsed = ParsedResume(raw_text=text)

    if match := _EMAIL.search(text):
        parsed.identity["email"] = match.group(0)
    if match := _PHONE.search(text):
        parsed.identity["phone"] = match.group(0).strip()
    lines = text.split("\n")
    for line in lines[:5]:
        stripped = line.strip()
        if stripped and not _EMAIL.search(stripped) and len(stripped.split()) <= 5:
            parsed.identity["name"] = stripped
            break

    current = ProfileItemKind.ROLE
    offset = 0
    #: Later lines are older on a conventional resume, so prominence decays.
    #: FR-M-A3 weights the plan toward recent, prominently-claimed experience.
    total = max(1, len(lines))
    for index, line in enumerate(lines):
        start = offset
        offset += len(line) + 1
        stripped = line.strip()
        if not stripped:
            continue

        if len(stripped) < 48 and (section := _section_for(stripped)):
            current = section
            continue

        is_bullet = bool(_BULLET.match(line))
        content = _BULLET.sub("", stripped)
        if len(content) < 12:
            continue

        prominence = max(0, 10 - (index * 10 // total))
        looks_like_skill_list = "," in content or "·" in content
        if current is ProfileItemKind.SKILL and not is_bullet and looks_like_skill_list:
            for skill in re.split(r"[,;·|]", content):
                skill = skill.strip()
                if 1 < len(skill) <= 40:
                    parsed.items.append(
                        ExtractedItem(
                            kind=ProfileItemKind.SKILL,
                            payload={"skill": skill},
                            source_text=content[:500],
                            span=(start, start + len(line)),
                            prominence=prominence,
                        )
                    )
            continue

        payload: dict = {"text": content[:600]}
        if years := _YEAR.findall(content):
            payload["years"] = sorted(set(years))[:4]
        # Clipped on a word boundary, not a character index. These two fields
        # are what question framing quotes back at the candidate, and a raw
        # slice produced "You mentioned Developed custom web applications and
        # academic projects usin — with that in mind:" in a real report. The
        # framing layer cannot repair that: by the time it sees the value, the
        # word is already gone.
        if current is ProfileItemKind.PROJECT:
            payload["name"] = _clip(content.split(":")[0] if ":" in content else content)
        if current is ProfileItemKind.ROLE:
            payload["title"] = _clip(content.split(",")[0] if "," in content else content)

        parsed.items.append(
            ExtractedItem(
                kind=current,
                payload=payload,
                source_text=content[:500],
                span=(start, start + len(line)),
                prominence=prominence,
            )
        )

    return parsed


# ---------------------------------------------------------------------------
# Persistence (worker-side, sync session)
# ---------------------------------------------------------------------------
def parse_resume_version(db: Session, version_id) -> DocumentStatus:  # type: ignore[no-untyped-def]
    version = db.get(ResumeVersion, version_id)
    if version is None:
        raise LookupError(f"resume version {version_id} not found")
    if version.status == DocumentStatus.READY:
        return DocumentStatus.READY  # idempotent consumer (NFR-S6)

    version.status = DocumentStatus.PARSING
    db.flush()

    try:
        content = storage.download_bytes(version.object_key)
        text = extract_text(content, version.content_type)
    except Exception as exc:
        version.status = DocumentStatus.FAILED
        version.failure_reason = str(exc)[:500]
        logger.error("resume_parse_failed", version_id=str(version_id), error=str(exc))
        return DocumentStatus.FAILED

    # NFR-INJ5: flag instruction-like content for review. Defence-in-depth --
    # the architectural control (§1.2) does not depend on this catching anything.
    flags = detect_injection(text)
    version.injection_flags = flags

    parsed = parse_resume_text(text)
    profile = ResumeProfile(
        resume_version_id=version.id,
        identity=parsed.identity,
        raw_text_chars=len(parsed.raw_text),
    )
    profile.items = [
        ProfileItem(
            ordinal=index,
            kind=item.kind.value,
            payload=item.payload,
            source_text=item.source_text,
            source_span_start=item.span[0],
            source_span_end=item.span[1],
            prominence=item.prominence,
        )
        for index, item in enumerate(parsed.items[:200])
    ]
    db.add(profile)

    # The resume equivalent of FR-J4's thin-JD warning. A sparse resume no
    # longer shortens the interview -- planning tops up -- so without this the
    # candidate would never learn that their document is the reason the
    # questions drifted away from their own experience. Same gap a recruiter
    # would hit, surfaced while they can still fix it.
    all_competencies = db.query(Competency).filter(Competency.active.is_(True)).all()
    quality = resume_quality.assess(
        competency_ids=match_competency_ids(all_competencies, parsed.raw_text),
        item_kinds=[item.kind.value for item in parsed.items],
        total_chars=len(parsed.raw_text),
    )
    profile.quality = quality.to_dict()

    version.parsed_at = datetime.now(UTC)
    version.status = DocumentStatus.QUARANTINED if flags else DocumentStatus.READY
    logger.info(
        "resume_parsed",
        version_id=str(version_id),
        items=len(profile.items),
        injection_flags=len(flags),
        quality=quality.rating,
        competencies=quality.competencies_found,
    )
    return DocumentStatus(version.status)


def match_competency_ids(competencies: list[Competency], text: str) -> list[str]:
    """Slug-token overlap against the closed taxonomy (IR-4).

    Extracted from the JD parser so the resume path rates itself with exactly
    the matcher that will later choose its questions -- two implementations
    would let the rating and the plan disagree, which is worse than no rating.
    """
    lowered = text.lower()
    found: list[str] = []
    for competency in competencies:
        terms = {part for part in competency.competency_id.split("-") if len(part) > 3}
        if not terms:
            continue
        hits = [term for term in terms if term in lowered]
        if len(hits) >= max(1, len(terms) // 2):
            found.append(competency.competency_id)
    return found


def parse_jd_version(db: Session, version_id) -> DocumentStatus:  # type: ignore[no-untyped-def]
    """FR-J2 + FR-J4.

    Requirement matching is slug-token overlap against the closed taxonomy, so
    the output is *already* constrained to valid competency ids -- the same
    IR-4 discipline as reduction, applied at intake.
    """
    version = db.get(JDVersion, version_id)
    if version is None:
        raise LookupError(f"jd version {version_id} not found")
    if version.status == DocumentStatus.READY:
        return DocumentStatus.READY

    version.status = DocumentStatus.PARSING
    db.flush()

    text = normalise(version.raw_text)
    flags = detect_injection(text)
    version.injection_flags = flags

    lowered = text.lower()
    competencies = db.query(Competency).filter(Competency.active.is_(True)).all()

    matched: list[tuple[str, str, str]] = []
    for competency in competencies:
        terms = {part for part in competency.competency_id.split("-") if len(part) > 3}
        if not terms:
            continue
        hits = [term for term in terms if term in lowered]
        if len(hits) >= max(1, len(terms) // 2):
            index = lowered.find(hits[0])
            snippet = text[max(0, index - 60) : index + 120].strip()
            required = any(
                marker in snippet.lower()
                for marker in ("required", "must have", "essential", "strong")
            )
            matched.append(
                (
                    competency.competency_id,
                    RequirementWeight.REQUIRED if required else RequirementWeight.PREFERRED,
                    snippet,
                )
            )

    profile = JDProfile(
        jd_version_id=version.id,
        role_title=(text.split("\n", 1)[0][:200] or None),
        responsibilities=[
            line.strip()[:300]
            for line in text.split("\n")
            if _BULLET.match(line) and len(line.strip()) > 12
        ][:20],
    )
    profile.requirements = [
        JDRequirement(ordinal=index, competency_id=cid, weight=weight, source_text=snippet)
        for index, (cid, weight, snippet) in enumerate(sorted(set(matched))[:25])
    ]
    db.add(profile)

    # FR-J4: a thin JD warns and prompts for enrichment rather than silently
    # producing a weak interview.
    version.thin = len(profile.requirements) < 3
    version.parsed_at = datetime.now(UTC)
    version.status = DocumentStatus.QUARANTINED if flags else DocumentStatus.READY
    logger.info(
        "jd_parsed",
        version_id=str(version_id),
        requirements=len(profile.requirements),
        thin=version.thin,
    )
    return DocumentStatus(version.status)
