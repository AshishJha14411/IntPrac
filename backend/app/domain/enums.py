"""Closed vocabularies.

These are enums because they are the boundary the spec relies on: reduction may
only emit values from here (IR-4), and anything outside is discarded rather
than trusted. Stored as strings so a migration -- not a silent cast -- is
required to change them.
"""

from __future__ import annotations

from enum import StrEnum


class Seniority(StrEnum):
    FRESHER = "fresher"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"


class Domain(StrEnum):
    CS_FUNDAMENTALS = "cs-fundamentals"
    OS_AND_SYSTEMS = "os-and-systems"
    COMPUTER_ARCHITECTURE = "computer-architecture"
    NETWORKING = "networking"
    DATABASES = "databases"
    BACKEND_ENGINEERING = "backend-engineering"
    FRONTEND_ENGINEERING = "frontend-engineering"
    SYSTEM_DESIGN = "system-design"
    DEVOPS_CLOUD = "devops-cloud"
    SECURITY = "security"
    TESTING_AND_PRACTICE = "testing-and-practice"
    LANGUAGE_RUNTIME = "language-runtime"
    AI_LLM_ENGINEERING = "ai-llm-engineering"
    BEHAVIOURAL = "behavioural"


class InterviewMode(StrEnum):
    """§5. All three modes are the same pipeline with a different reduction input."""

    RESUME = "resume"
    JD = "jd"
    COMBINED = "combined"


class SessionPurpose(StrEnum):
    """§1.1 -- same engine, different visibility rules."""

    PRACTICE = "practice"
    OFFICIAL = "official"


class SessionStatus(StrEnum):
    """FR-S1. Transitions are explicit and audited; illegal ones are rejected."""

    CREATED = "created"
    PLANNED = "planned"
    CONSENT_PENDING = "consent_pending"
    DEVICE_CHECK = "device_check"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    GRADED = "graded"
    PUBLISHED = "published"
    REVIEWED = "reviewed"


class QuestionStatus(StrEnum):
    PENDING = "pending"
    ASKED = "asked"
    ANSWERED = "answered"
    SKIPPED = "skipped"


class ConceptWeight(StrEnum):
    CORE = "core"
    SUPPORTING = "supporting"
    BONUS = "bonus"


class Verdict(StrEnum):
    """FR-E2. Exactly one verdict per expected concept, always with evidence."""

    COVERED = "covered"
    PARTIAL = "partial"
    MISSING = "missing"
    CONTRADICTED = "contradicted"


class RubricFamily(StrEnum):
    """FR-B1a: behavioural answers are not graded by concept coverage."""

    CONCEPT = "concept"
    NARRATIVE = "narrative"


class QuestionArchetype(StrEnum):
    """FR-M-A2 / FR-M-B2."""

    DEPTH = "depth"
    DECISION = "decision"
    CONTRIBUTION = "contribution"
    EDGE = "edge"
    SCENARIO = "scenario"
    NARRATIVE = "narrative"


class HintLevel(StrEnum):
    """FR-E4a. Never past L3, and never supplies terminology."""

    L1_REFRAME = "l1_reframe"
    L2_SIGNPOST = "l2_signpost"
    L3_PARTIAL_REVEAL = "l3_partial_reveal"


class HintTrigger(StrEnum):
    REQUESTED = "requested"
    SILENCE = "silence"
    OFF_TRACK = "off_track"
    #: The answer never reached a core concept, so the follow-up signposted it
    #: rather than reporting it missing unasked (FR-E5a). Distinct from
    #: ``requested`` because nobody asked for help -- and the audit trail
    #: (FR-E4d) should say which of those happened.
    UNCOVERED = "uncovered"


class AnswerInputMode(StrEnum):
    TYPED = "typed"
    SPEECH = "speech"


class FitLevel(StrEnum):
    """FR-M-C1."""

    STRONG = "strong"
    PARTIAL = "partial"
    ABSENT = "absent"


class DocumentStatus(StrEnum):
    """FR-R3: the UI never blocks on parsing."""

    UPLOADED = "uploaded"
    PARSING = "parsing"
    READY = "ready"
    FAILED = "failed"
    QUARANTINED = "quarantined"  # NFR-INJ5


class ProfileItemKind(StrEnum):
    SKILL = "skill"
    ROLE = "role"
    PROJECT = "project"
    EDUCATION = "education"
    CERTIFICATION = "certification"


class RequirementWeight(StrEnum):
    REQUIRED = "required"
    PREFERRED = "preferred"


class OrgRole(StrEnum):
    """FR-A4: roles are per-org, never global."""

    OWNER = "owner"
    ADMIN = "admin"
    REVIEWER = "reviewer"
    MEMBER = "member"


class CostKind(StrEnum):
    """NFR-C1: a session whose cost is unknown is a bug."""

    LLM_INPUT_TOKENS = "llm_input_tokens"
    LLM_OUTPUT_TOKENS = "llm_output_tokens"
    STT_SECONDS = "stt_seconds"
    TTS_CHARACTERS = "tts_characters"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"


class EvaluationStatus(StrEnum):
    """FR-E6a: malformed grader output is quarantined, never silently defaulted."""

    PENDING = "pending"
    COMPLETE = "complete"
    QUARANTINED = "quarantined"
