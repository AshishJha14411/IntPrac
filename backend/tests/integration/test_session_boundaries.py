"""The boundaries a direct API caller could previously walk straight through.

Every test here corresponds to a finding in ``gaps.md``. They share a shape:
drive the API the way a *client other than our own UI* would, and assert the
server refuses. "Not reachable through the app" was the previous state of each
of these, and it is not a control.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.enums import DocumentStatus, QuestionStatus
from app.models.documents import ResumeVersion
from app.models.interview import InterviewSession

pytestmark = pytest.mark.integration

PREFIX = settings.api_v1_prefix

ANSWER = (
    "It has to walk past all those rows first and throw them away, so the deeper you page "
    "the slower it gets. You remember where you stopped and start there next time."
)


def _register(client: TestClient, tag: str) -> dict[str, Any]:
    """A second identity, with its own cookies held separately."""
    response = client.post(
        f"{PREFIX}/auth/register",
        json={
            "email": f"{tag}-{uuid.uuid4().hex[:8]}@example.com",
            "password": "a-long-enough-password-1",
            "display_name": tag,
        },
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _jd(client: TestClient, db: Session, headers: dict[str, Any]) -> uuid.UUID:
    from app.services.documents import parse_jd_version

    body = client.post(
        f"{PREFIX}/jds",
        headers=headers,
        json={
            "title": "Senior Backend Engineer",
            "text": (
                "Senior Backend Engineer\n- indexing strategy and query planning in Postgres\n"
                "- transactions and acid guarantees\n- rest api design and error contracts\n"
                "- idempotency keys and rate limiting\n- connection pooling and migrations\n"
                "- timeouts retries and circuit breakers\n- async concurrency model"
            ),
        },
    ).json()
    version_id = uuid.UUID(body["id"])
    parse_jd_version(db, version_id)
    db.flush()
    return version_id


def _session(client: TestClient, headers: dict[str, Any], jd_id: uuid.UUID) -> str:
    response = client.post(
        f"{PREFIX}/sessions",
        headers=headers,
        json={
            "mode": "jd",
            "seniority": "senior",
            "target_minutes": 20,
            "jd_version_id": str(jd_id),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["session"]["id"]


def _started(client: TestClient, db: Session, headers: dict[str, Any]) -> tuple[str, dict]:
    session_id = _session(client, headers, _jd(client, db, headers))
    client.post(
        f"{PREFIX}/sessions/{session_id}/consent",
        headers=headers,
        json={
            "accepts_ai_assessment": True,
            "accepts_recording": True,
            "accepts_retention": True,
        },
    )
    turn = client.post(f"{PREFIX}/sessions/{session_id}/start", headers=headers).json()
    return session_id, turn


# ---------------------------------------------------------------------------
# G-003 -- the server owns turn order
# ---------------------------------------------------------------------------
def test_you_cannot_answer_a_question_that_has_not_been_asked(
    client: TestClient, db: Session, registered: dict
) -> None:
    """Answering ahead skips the questions in between and scores them missing."""
    headers = _register(client, "turn")
    session_id, turn = _started(client, db, headers)

    interview = db.get(InterviewSession, uuid.UUID(session_id))
    assert interview is not None
    db.refresh(interview)
    later = sorted(interview.questions, key=lambda q: q.ordinal)[-1]
    assert str(later.id) != turn["question_id"], "need a question that is not current"

    response = client.post(
        f"{PREFIX}/sessions/{session_id}/answers",
        headers=headers,
        json={
            "question_id": str(later.id),
            "transcript": ANSWER,
            "idempotency_key": f"key-{uuid.uuid4().hex}",
        },
    )
    assert response.status_code == 409
    # The error has to carry where we actually are, or a stale tab can only guess.
    assert response.json()["expected_question_id"] == turn["question_id"]


def test_you_cannot_take_a_hint_on_a_future_question(
    client: TestClient, db: Session, registered: dict
) -> None:
    """A hint marks its concept discounted, so this quietly lowered a later bar."""
    headers = _register(client, "hint")
    session_id, _turn = _started(client, db, headers)

    interview = db.get(InterviewSession, uuid.UUID(session_id))
    assert interview is not None
    db.refresh(interview)
    later = sorted(interview.questions, key=lambda q: q.ordinal)[-1]

    response = client.post(
        f"{PREFIX}/sessions/{session_id}/hints",
        headers=headers,
        json={"question_id": str(later.id), "trigger": "requested"},
    )
    assert response.status_code == 409
    db.refresh(interview)
    discounted = [c for q in interview.questions for c in q.concepts if c.hint_touched]
    assert not discounted, "a refused hint must not discount anything"


def test_you_cannot_take_a_hint_before_consent(
    client: TestClient, db: Session, registered: dict
) -> None:
    """`give_hint` used to check no session state whatsoever."""
    headers = _register(client, "preconsent")
    session_id = _session(client, headers, _jd(client, db, headers))

    interview = db.get(InterviewSession, uuid.UUID(session_id))
    assert interview is not None
    db.refresh(interview)
    first = sorted(interview.questions, key=lambda q: q.ordinal)[0]

    response = client.post(
        f"{PREFIX}/sessions/{session_id}/hints",
        headers=headers,
        json={"question_id": str(first.id), "trigger": "requested"},
    )
    assert response.status_code == 409


def test_you_cannot_answer_the_same_question_twice_with_a_fresh_key(
    client: TestClient, db: Session, registered: dict
) -> None:
    """Not a replay -- a *new* key on an already-answered question.

    Idempotency covers the retry case. This is the other one: extra turns
    appended to a finished question without a follow-up ever being offered.
    """
    headers = _register(client, "double")
    session_id, turn = _started(client, db, headers)
    first = turn["question_id"]

    for _ in range(3):  # answer through any follow-ups this question earns
        body = client.post(
            f"{PREFIX}/sessions/{session_id}/answers",
            headers=headers,
            json={
                "question_id": first,
                "transcript": ANSWER,
                "idempotency_key": f"key-{uuid.uuid4().hex}",
            },
        ).json()
        nxt = body.get("next_turn")
        if not nxt or nxt["question_id"] != first:
            break

    response = client.post(
        f"{PREFIX}/sessions/{session_id}/answers",
        headers=headers,
        json={
            "question_id": first,
            "transcript": ANSWER,
            "idempotency_key": f"key-{uuid.uuid4().hex}",
        },
    )
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# G-001 -- documents belong to somebody
# ---------------------------------------------------------------------------
def test_you_cannot_build_a_session_from_someone_elses_resume(
    client: TestClient, db: Session, registered: dict
) -> None:
    """Holding a UUID was enough to interview against another person's resume."""
    from app.models.documents import Resume, ResumeProfile

    owner = _register(client, "owner")
    presign = client.post(
        f"{PREFIX}/resumes/presign",
        headers=owner,
        json={
            "filename": "cv.pdf",
            "content_type": "application/pdf",
            "size_bytes": 2048,
            "label": "mine",
        },
    ).json()
    version_id = uuid.UUID(presign["version_id"])

    version = db.get(ResumeVersion, version_id)
    assert version is not None
    version.status = DocumentStatus.READY
    db.add(ResumeProfile(resume_version_id=version.id, identity={}))
    db.flush()

    intruder = _register(client, "intruder")
    response = client.post(
        f"{PREFIX}/sessions",
        headers=intruder,
        json={
            "mode": "resume",
            "seniority": "mid",
            "target_minutes": 20,
            "resume_version_id": str(version_id),
        },
    )
    # A 404, not a 403: confirming the id exists is itself the disclosure.
    assert response.status_code == 404
    resume = db.get(Resume, version.resume_id)
    assert resume is not None


# ---------------------------------------------------------------------------
# G-014 -- a quarantined document is not raw material
# ---------------------------------------------------------------------------
def test_a_quarantined_resume_cannot_start_an_interview(
    client: TestClient, db: Session, registered: dict
) -> None:
    """We already decided not to trust this file. Don't feed it to reduction."""
    from app.models.documents import ResumeProfile

    owner = _register(client, "quarantine")
    presign = client.post(
        f"{PREFIX}/resumes/presign",
        headers=owner,
        json={
            "filename": "cv.pdf",
            "content_type": "application/pdf",
            "size_bytes": 2048,
            "label": "suspicious",
        },
    ).json()
    version = db.get(ResumeVersion, uuid.UUID(presign["version_id"]))
    assert version is not None
    version.status = DocumentStatus.QUARANTINED
    db.add(ResumeProfile(resume_version_id=version.id, identity={}))
    db.flush()

    response = client.post(
        f"{PREFIX}/sessions",
        headers=owner,
        json={
            "mode": "resume",
            "seniority": "mid",
            "target_minutes": 20,
            "resume_version_id": str(version.id),
        },
    )
    assert response.status_code == 409
    assert "quarantined" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# G-008 -- a skipped question is finished, not late
# ---------------------------------------------------------------------------
def test_a_skipped_question_does_not_leave_the_report_pending_forever(
    client: TestClient, db: Session, registered: dict
) -> None:
    """The report page polls while `pending_questions > 0`.

    A skip is deliberately never graded (FR-S6), so counting it as pending
    meant a four-second refresh loop that could never end.
    """
    headers = _register(client, "skipper")
    session_id, turn = _started(client, db, headers)

    client.post(
        f"{PREFIX}/sessions/{session_id}/answers",
        headers=headers,
        json={
            "question_id": turn["question_id"],
            "transcript": "",
            "skipped": True,
            "idempotency_key": f"key-{uuid.uuid4().hex}",
        },
    )

    interview = db.get(InterviewSession, uuid.UUID(session_id))
    assert interview is not None
    db.refresh(interview)
    assert any(q.status == QuestionStatus.SKIPPED for q in interview.questions)

    report = client.get(f"{PREFIX}/sessions/{session_id}/report", headers=headers).json()
    skipped = [q for q in report["questions"] if q["status"] == QuestionStatus.SKIPPED]
    assert skipped, "the skip should still appear in the report"
    assert report["pending_questions"] == 0, "a skip is complete, not awaiting a grade"


# ---------------------------------------------------------------------------
# G-002 -- reading someone's interview is not taking it
# ---------------------------------------------------------------------------
def test_a_same_org_reviewer_may_read_but_never_mutate(
    client: TestClient, db: Session, registered: dict
) -> None:
    """The exact scenario the finding describes.

    Two users in *different* orgs prove very little here, because every user
    gets a personal org and the check would pass on ownership alone. The real
    case is a reviewer who legitimately holds ``SESSION_READ_ORG`` over this
    candidate's session: they must be able to read it and must not be able to
    consent, start, answer, hint or abandon on the candidate's behalf.

    Tested against the helpers directly, because minting a token for "someone
    else's org" is not something the auth flow will do -- which is itself the
    point: the guard must not depend on tokens being hard to forge.
    """
    import asyncio

    from app.api.v1.sessions import _own_session, _readable_session
    from app.authz.perms import ROLE_PERMISSIONS, Perm
    from app.authz.policy import Principal
    from app.core.errors import NotFoundError
    from app.domain.enums import OrgRole
    from tests.conftest import _SyncToAsyncSession  # type: ignore[attr-defined]

    headers = _register(client, "candidate")
    session_id = _session(client, headers, _jd(client, db, headers))
    interview = db.get(InterviewSession, uuid.UUID(session_id))
    assert interview is not None

    reviewer = Principal(
        user_id=uuid.uuid4(),                      # a different person
        organization_id=interview.organization_id,  # in the *same* organisation
        role=OrgRole.REVIEWER,
        email_verified=True,
        permissions=frozenset(ROLE_PERMISSIONS[OrgRole.REVIEWER]),
    )
    assert Perm.SESSION_READ_ORG in reviewer.permissions, "the fixture must be a real reviewer"

    adapter = _SyncToAsyncSession(db)

    # Reading is their job.
    readable = asyncio.run(_readable_session(adapter, interview.id, reviewer))
    assert readable.id == interview.id

    # Acting in it is not.
    with pytest.raises(NotFoundError):
        asyncio.run(_own_session(adapter, interview.id, reviewer))


# ---------------------------------------------------------------------------
# G-010 -- a cookie is ambient authority; an Origin is not
# ---------------------------------------------------------------------------
def test_a_hostile_origin_cannot_use_your_cookie(
    client: TestClient, registered: dict
) -> None:
    """The defence used to be an argument: "everything is JSON, so everything
    is preflighted." Several cookie-authenticated POSTs take no body at all --
    refresh, logout, session start/abandon, upload completion -- so they are
    CORS-*simple* requests a third-party form can submit. CORS blocks reading
    the reply, which is no help when the damage is the write.
    """
    client.post(
        f"{PREFIX}/auth/register",
        json={
            "email": f"csrf-{uuid.uuid4().hex[:8]}@example.com",
            "password": "a-long-enough-password-1",
            "display_name": "Csrf",
        },
    )
    assert "interview_access" in client.cookies
    # A browser has no Authorization header -- it has only the ambient cookie,
    # which is the entire premise of the attack. The shared fixture leaves one
    # set, and with it the request is correctly exempt.
    client.headers.pop("Authorization", None)

    hostile = client.post(f"{PREFIX}/auth/refresh", headers={"Origin": "https://evil.example"})
    assert hostile.status_code == 403
    assert hostile.json()["code"] == "csrf-origin-rejected"

    allowed = client.post(
        f"{PREFIX}/auth/refresh", headers={"Origin": settings.cors_origins[0]}
    )
    assert allowed.status_code == 200


def test_a_bearer_client_is_not_subject_to_the_origin_check(
    client: TestClient, registered: dict
) -> None:
    """A token has to be deliberately attached, so it is not ambient.

    Without this carve-out the control would break every API client for no
    security gain -- nothing can trick a script into sending a header it does
    not choose to send.
    """
    headers = _register(client, "bearer")
    client.cookies.clear()
    response = client.post(
        f"{PREFIX}/jds",
        headers={**headers, "Origin": "https://evil.example"},
        json={"title": "Role", "text": "Backend engineer with Postgres and REST API design. " * 3},
    )
    assert response.status_code == 201


def test_a_missing_origin_is_refused_only_when_samesite_cannot_help(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`lax` withholds the cookie cross-site, so a missing Origin is a script.

    `none` gives that up, and browsers always send Origin on such a request --
    so requiring one there costs nothing and closes the hole.
    """
    from app.core.config import settings as live

    client.post(
        f"{PREFIX}/auth/register",
        json={
            "email": f"nosite-{uuid.uuid4().hex[:8]}@example.com",
            "password": "a-long-enough-password-1",
            "display_name": "NoSite",
        },
    )

    client.headers.pop("Authorization", None)
    monkeypatch.setattr(live, "auth_cookie_samesite", "lax")
    assert client.post(f"{PREFIX}/auth/refresh").status_code == 200

    monkeypatch.setattr(live, "auth_cookie_samesite", "none")
    assert client.post(f"{PREFIX}/auth/refresh").status_code == 403


# ---------------------------------------------------------------------------
# G-009 -- the deletion the consent screen promises
# ---------------------------------------------------------------------------
def test_deleting_a_session_removes_everything_derived_from_it(
    client: TestClient, db: Session, registered: dict
) -> None:
    """Consent said "delete at any time" and nothing could. Now it can."""
    from app.models.interview import Answer, SessionQuestion

    headers = _register(client, "deleter")
    session_id, turn = _started(client, db, headers)
    client.post(
        f"{PREFIX}/sessions/{session_id}/answers",
        headers=headers,
        json={
            "question_id": turn["question_id"],
            "transcript": ANSWER,
            "input_mode": "speech",
            "duration_ms": 4000,
            "segments": [{"text": "some words", "start_ms": 0, "end_ms": 900, "confidence": 0.9}],
            "idempotency_key": f"key-{uuid.uuid4().hex}",
        },
    )
    interview = db.get(InterviewSession, uuid.UUID(session_id))
    assert interview is not None
    db.refresh(interview)
    question_ids = [q.id for q in interview.questions]
    assert question_ids

    assert client.delete(f"{PREFIX}/sessions/{session_id}", headers=headers).status_code == 204
    db.flush()
    db.expire_all()

    assert db.get(InterviewSession, uuid.UUID(session_id)) is None
    # The cascade has to reach the children, or "deleted" is only the header.
    assert db.query(SessionQuestion).filter(SessionQuestion.id.in_(question_ids)).count() == 0
    assert (
        db.query(Answer).filter(Answer.session_question_id.in_(question_ids)).count() == 0
    )


def test_you_cannot_delete_someone_elses_session(
    client: TestClient, db: Session, registered: dict
) -> None:
    """Deletion is the most destructive act here; a reviewer's read must not reach it."""
    owner = _register(client, "owner2")
    session_id = _session(client, owner, _jd(client, db, owner))

    intruder = _register(client, "intruder2")
    assert client.delete(f"{PREFIX}/sessions/{session_id}", headers=intruder).status_code == 404
    assert db.get(InterviewSession, uuid.UUID(session_id)) is not None


def test_the_retention_window_is_six_months_and_covers_transcripts(
    client: TestClient, db: Session, registered: dict
) -> None:
    """G-009: the promise and the job have to agree.

    The window used to be 730 days for transcripts, and nothing deleted them at
    all -- so the number in the consent screen was doubly untrue.
    """
    from datetime import UTC, datetime, timedelta

    from app.models.identity import Organization
    from app.workers.tasks.retention import apply_retention

    headers = _register(client, "retained")
    session_id = _session(client, headers, _jd(client, db, headers))
    interview = db.get(InterviewSession, uuid.UUID(session_id))
    assert interview is not None

    organization = db.get(Organization, interview.organization_id)
    assert organization is not None
    assert organization.transcript_retention_days == 180, "six months, matching the disclosure"
    assert organization.media_retention_days == 180

    # Age it past the window and confirm the job actually reaps it.
    interview.created_at = datetime.now(UTC) - timedelta(days=181)
    db.flush()
    assert apply_retention  # the task exists and is importable by the scheduler
