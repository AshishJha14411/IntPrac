"""Import every model so Alembic autogenerate sees the full metadata.

A model that is not imported here is a table Alembic will happily *drop*.
"""

from app.db.base import Base
from app.models.content import BankQuestion, BankRubricConcept, Competency, GoldenAnswer
from app.models.documents import (
    JDProfile,
    JDRequirement,
    JDVersion,
    JobDescription,
    ProfileItem,
    Resume,
    ResumeProfile,
    ResumeVersion,
)
from app.models.evaluation import ConceptAssessment, Evaluation
from app.models.identity import Consent, Organization, OrgMember, RefreshToken, User
from app.models.interview import (
    Answer,
    FitMapEntry,
    Hint,
    InterviewSession,
    Posting,
    ReductionResult,
    RubricConcept,
    SessionQuestion,
    TranscriptSegment,
)
from app.models.oauth import OAuthAccount
from app.models.ops import AuditLog, OutboxEvent, UsageCost

__all__ = [
    "Answer",
    "AuditLog",
    "BankQuestion",
    "BankRubricConcept",
    "Base",
    "Competency",
    "ConceptAssessment",
    "Consent",
    "Evaluation",
    "FitMapEntry",
    "GoldenAnswer",
    "Hint",
    "InterviewSession",
    "JDProfile",
    "JDRequirement",
    "JDVersion",
    "JobDescription",
    "OAuthAccount",
    "OrgMember",
    "Organization",
    "OutboxEvent",
    "Posting",
    "ProfileItem",
    "ReductionResult",
    "RefreshToken",
    "Resume",
    "ResumeProfile",
    "ResumeVersion",
    "RubricConcept",
    "SessionQuestion",
    "TranscriptSegment",
    "UsageCost",
    "User",
]
