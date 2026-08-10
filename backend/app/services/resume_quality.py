"""How much of an interview a resume can actually support, and why.

The problem this names. A 45-minute session on a sparse resume planned three
questions, because reduction can only select competencies the document
actually evidences -- across real usage, resumes yielded 5.2 competencies
against a job description's 7.1. Planning now tops up so the session is never
short, but that hides the signal rather than giving it to the person who can
act on it.

So the resume gets a rating, and the rating is **feedback, not a gate**. A
sparse resume still produces a full interview; it also produces a short list of
what a reader could not find. That is useful twice over: it makes the practice
better, and it is the same gap a recruiter would hit.

Deliberately deterministic -- counting, not judging. Three reasons: it costs
nothing on a path that runs for every upload (§8.3), the advice is the same
every time so it can be argued with, and this reads candidate prose, which is
the one input class the system treats as hostile (FR-R8). A rule that counts
extracted structure cannot be talked into anything by the document it is
reading.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.enums import ProfileItemKind

#: Below this many distinct competencies, a resume cannot fill a normal
#: session on its own. Chosen from measurement rather than taste: the observed
#: mean for resumes is 5.2, and 20-minute sessions ask for 10.
SPARSE_COMPETENCIES = 6

#: A resume with fewer extracted items than this is usually a one-page summary
#: or a scan whose text did not come through.
THIN_ITEMS = 8


@dataclass(frozen=True, slots=True)
class ResumeQuality:
    """A rating a candidate can act on, not a score to feel bad about."""

    rating: str  # "strong" | "workable" | "sparse"
    competencies_found: int
    items_found: int
    #: Concrete, ordered by how much each would change the outcome.
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "rating": self.rating,
            "competencies_found": self.competencies_found,
            "items_found": self.items_found,
            "suggestions": self.suggestions,
        }


def assess(
    *, competency_ids: list[str], item_kinds: list[str], total_chars: int
) -> ResumeQuality:
    """Rate a parsed resume by what could be extracted from it.

    Everything here is derived from the *parsed profile*, never from the raw
    prose -- so this stays on the safe side of the trust boundary alongside
    everything else that is not ``reduction``.
    """
    found = len(set(competency_ids))
    items = len(item_kinds)
    kinds = set(item_kinds)
    suggestions: list[str] = []

    if found < SPARSE_COMPETENCIES:
        suggestions.append(
            f"Only {found} technical topic(s) could be identified. Name the specific "
            "things you worked on — indexing, caching, retries, schema migrations — "
            "rather than the tools. A reader looking for depth needs the topic, not "
            "the logo."
        )
    if ProfileItemKind.PROJECT.value not in kinds and ProfileItemKind.ROLE.value not in kinds:
        suggestions.append(
            "No roles or projects were recognised. Use clear section headings "
            "(Experience, Projects) — a single block of prose is hard to read for "
            "a person too."
        )
    if items < THIN_ITEMS:
        suggestions.append(
            "There is very little detail to work from. One line per achievement, "
            "saying what changed and how you know, gives far more to ask about."
        )
    # Short text *and* few items together, never short text alone. A dense
    # one-page resume is short and fine; the signal worth raising is "the PDF
    # did not extract", and that shows up as both. Firing on length alone
    # produced a resume rated `strong` while being told its text was too short,
    # which teaches people to ignore the advice.
    if total_chars < 1200 and items < THIN_ITEMS:
        suggestions.append(
            "Very little text came out of this file. If it is a design-heavy PDF or "
            "a scan, it may not be machine-readable — exporting from your editor "
            "rather than printing to an image usually fixes it."
        )
    if ProfileItemKind.SKILL.value in kinds and found < SPARSE_COMPETENCIES:
        suggestions.append(
            "There is a skills list, but skills alone don't say what you *did* with "
            "them. Tie two or three to a concrete piece of work."
        )

    if found >= SPARSE_COMPETENCIES and items >= THIN_ITEMS:
        rating = "strong"
    elif found >= 3:
        rating = "workable"
    else:
        rating = "sparse"

    if rating == "strong" and not suggestions:
        suggestions.append(
            "Plenty to work with. The interview will follow the topics your "
            "experience actually evidences."
        )
    return ResumeQuality(
        rating=rating,
        competencies_found=found,
        items_found=items,
        suggestions=suggestions,
    )
