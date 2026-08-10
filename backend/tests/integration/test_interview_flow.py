"""The P0 exit criterion, as a test.

"You can take a real interview on your own resume and the gaps it reports are
ones you agree with." The subjective half is a human's job; this covers the
mechanical half end to end: JD in -> plan -> consent -> answers -> grading ->
report, against the **real seeded bank**.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.enums import DocumentStatus, SessionStatus
from app.models.documents import JDVersion
from app.models.interview import InterviewSession
from app.services.documents import parse_jd_version
from app.services.grading import grade_answer

pytestmark = pytest.mark.integration

PREFIX = settings.api_v1_prefix

JD_TEXT = """
Senior Backend Engineer

We are looking for an engineer to own our API platform.

- Strong experience with indexing strategy and query planning in Postgres
- Deep understanding of transactions and acid guarantees
- Experience designing rest api design and error contract design
- Familiar with idempotency keys and rate limiting
- Comfortable with connection pooling and schema migration safety
- Understands authorization models and cache invalidation and stampede
- Works with async concurrency model daily
"""


def _create_jd(client: TestClient, db: Session) -> uuid.UUID:
    response = client.post(
        f"{PREFIX}/jds", json={"title": "Senior Backend Engineer", "text": JD_TEXT}
    )
    assert response.status_code == 201, response.text
    version_id = uuid.UUID(response.json()["id"])
    # The worker would normally do this; run it inline so the test owns the
    # ordering instead of racing a queue.
    assert parse_jd_version(db, version_id) is DocumentStatus.READY
    db.flush()
    return version_id


def test_full_practice_interview(client: TestClient, db: Session, registered: dict) -> None:
    jd_version_id = _create_jd(client, db)

    # ── plan ────────────────────────────────────────────────────────────────
    response = client.post(
        f"{PREFIX}/sessions",
        json={
            "mode": "jd",
            "seniority": "senior",
            "purpose": "practice",
            "target_minutes": 30,
            "jd_version_id": str(jd_version_id),
        },
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    session_id = plan["session"]["id"]
    assert plan["session"]["status"] == SessionStatus.CONSENT_PENDING
    assert plan["questions"], "reduction produced no answerable questions"
    # FR-P5: every question arrives with its rubric already resolved.
    # Asserted against the stored rubric, not the API response: the plan
    # deliberately no longer publishes concept counts, because telling a
    # candidate how many points a question has is a free hint. The invariant
    # still matters, so it is checked where it lives.
    planned = db.get(InterviewSession, uuid.UUID(session_id))
    assert planned is not None
    db.refresh(planned)
    for question in planned.questions:
        cores = [c for c in question.concepts if c.weight == "core"]
        assert len(cores) >= 2, f"{question.competency_id} shipped with {len(cores)} core concepts"

    # ── consent gate (FR-S2) ────────────────────────────────────────────────
    refused = client.post(
        f"{PREFIX}/sessions/{session_id}/consent",
        json={
            "accepts_ai_assessment": True,
            "accepts_recording": False,
            "accepts_retention": True,
        },
    )
    assert refused.status_code == 422, "partial consent must not open the gate"

    blocked = client.post(f"{PREFIX}/sessions/{session_id}/start")
    assert blocked.status_code == 409, "a session must not start before consent"

    accepted = client.post(
        f"{PREFIX}/sessions/{session_id}/consent",
        json={
            "accepts_ai_assessment": True,
            "accepts_recording": True,
            "accepts_retention": True,
        },
    )
    assert accepted.status_code == 200, accepted.text

    # ── turn loop ───────────────────────────────────────────────────────────
    turn = client.post(f"{PREFIX}/sessions/{session_id}/start").json()
    assert turn["prompt"]
    assert turn["remaining_minutes"] > 0

    answered = 0
    while True:
        response = client.post(
            f"{PREFIX}/sessions/{session_id}/answers",
            json={
                "question_id": turn["question_id"],
                # Long enough not to trip the shallow-answer follow-up.
                "transcript": (
                    "It has to walk past all those rows first and throw them away, so the "
                    "deeper you page the slower it gets. The fix is to remember where you "
                    "stopped and start there next time, and you need a tiebreaker or rows "
                    "repeat across pages."
                ),
                "idempotency_key": f"key-{uuid.uuid4().hex}",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        answered += 1
        if body["session_completed"]:
            break
        assert body["next_turn"], "a non-completed session must hand back the next turn"
        turn = body["next_turn"]
        assert answered < 30, "turn loop did not terminate"

    interview = db.get(InterviewSession, uuid.UUID(session_id))
    assert interview is not None
    db.refresh(interview)
    assert interview.status == SessionStatus.COMPLETED

    # ── grading (normally the worker; run inline) ───────────────────────────
    for question in interview.questions:
        for answer in question.answers:
            if answer.transcript:
                outcome = grade_answer(db, answer_id=answer.id)
                assert outcome.status.value == "complete", outcome
    db.flush()

    # ── report ──────────────────────────────────────────────────────────────
    report = client.get(f"{PREFIX}/sessions/{session_id}/report")
    assert report.status_code == 200, report.text
    payload = report.json()

    assert payload["graded_questions"] > 0
    assert payload["pending_questions"] == 0
    assert payload["recommendation"] in {"strong", "promising", "developing", "early"}
    assert payload["competencies"], "the report must roll up per competency"

    # FR-F2: per question, what was covered and what was missed.
    first = payload["questions"][0]
    assert first["band"] is not None
    assert first["raw_score"] is not None
    assert first["hint_adjusted_score"] is not None
    assert first["covered"] or first["missed"] or first["partial"]

    # FR-E2e: every non-missing verdict cites the candidate's own words.
    for question in payload["questions"]:
        for line in (*question["covered"], *question["partial"]):
            assert line["evidence_quote"], f"{line['concept_id']} has a verdict but no evidence"

    # FR-F3: the highest-leverage improvements, each with why it matters.
    for improvement in payload["top_improvements"]:
        assert improvement["why_it_matters"]
        assert improvement["what_to_add"]

    # NFR-C1: a session whose cost is unknown is a bug. The stub is free, so
    # the assertion is that the field exists and is a number, not that it's > 0.
    assert isinstance(payload["cost_usd"], (int, float))


def test_hint_ladder_never_leaks_terminology(
    client: TestClient, db: Session, registered: dict
) -> None:
    """FR-E4a/b: three rungs, and no rung hands over an acceptable signal."""
    jd_version_id = _create_jd(client, db)
    session_id = client.post(
        f"{PREFIX}/sessions",
        json={
            "mode": "jd",
            "seniority": "senior",
            "target_minutes": 30,
            "jd_version_id": str(jd_version_id),
        },
    ).json()["session"]["id"]
    client.post(
        f"{PREFIX}/sessions/{session_id}/consent",
        json={
            "accepts_ai_assessment": True,
            "accepts_recording": True,
            "accepts_retention": True,
        },
    )
    turn = client.post(f"{PREFIX}/sessions/{session_id}/start").json()

    levels = []
    for _ in range(3):
        response = client.post(
            f"{PREFIX}/sessions/{session_id}/hints",
            json={"question_id": turn["question_id"], "trigger": "requested"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        levels.append(body["level"])
        assert body["text"].strip()
        # FR-E4f: the candidate is told what a hint costs. No silent penalty.
        assert "hint-adjusted" in body["scoring_note"]

    assert levels == ["l1_reframe", "l2_signpost", "l3_partial_reveal"]

    # FR-E4a: never past L3.
    fourth = client.post(
        f"{PREFIX}/sessions/{session_id}/hints",
        json={"question_id": turn["question_id"], "trigger": "requested"},
    )
    assert fourth.status_code == 409


def test_short_answer_earns_a_followup(
    client: TestClient, db: Session, registered: dict
) -> None:
    """FR-E5a: a thin first answer is probed once before moving on."""
    jd_version_id = _create_jd(client, db)
    session_id = client.post(
        f"{PREFIX}/sessions",
        json={
            "mode": "jd",
            "seniority": "senior",
            "target_minutes": 30,
            "jd_version_id": str(jd_version_id),
        },
    ).json()["session"]["id"]
    client.post(
        f"{PREFIX}/sessions/{session_id}/consent",
        json={
            "accepts_ai_assessment": True,
            "accepts_recording": True,
            "accepts_retention": True,
        },
    )
    turn = client.post(f"{PREFIX}/sessions/{session_id}/start").json()

    response = client.post(
        f"{PREFIX}/sessions/{session_id}/answers",
        json={
            "question_id": turn["question_id"],
            "transcript": "Add an index.",
            "idempotency_key": f"key-{uuid.uuid4().hex}",
        },
    ).json()

    next_turn = response["next_turn"]
    assert next_turn["question_id"] == turn["question_id"], "follow-ups stay on the question"
    assert next_turn["is_followup"] is True
    assert next_turn["followup_prompt"]
    # FR-E5c: neutral, never leading.
    assert "isn't it" not in next_turn["followup_prompt"].lower()


def test_skipped_question_is_recorded_as_skipped(
    client: TestClient, db: Session, registered: dict
) -> None:
    """FR-S6: a skip is a skip, not a wrong answer."""
    jd_version_id = _create_jd(client, db)
    session_id = client.post(
        f"{PREFIX}/sessions",
        json={
            "mode": "jd",
            "seniority": "senior",
            "target_minutes": 30,
            "jd_version_id": str(jd_version_id),
        },
    ).json()["session"]["id"]
    client.post(
        f"{PREFIX}/sessions/{session_id}/consent",
        json={
            "accepts_ai_assessment": True,
            "accepts_recording": True,
            "accepts_retention": True,
        },
    )
    turn = client.post(f"{PREFIX}/sessions/{session_id}/start").json()

    body = client.post(
        f"{PREFIX}/sessions/{session_id}/answers",
        json={
            "question_id": turn["question_id"],
            "transcript": "",
            "skipped": True,
            "idempotency_key": f"key-{uuid.uuid4().hex}",
        },
    ).json()
    assert body["accepted"] is True

    interview = db.get(InterviewSession, uuid.UUID(session_id))
    assert interview is not None
    db.refresh(interview)
    skipped = [q for q in interview.questions if q.status == "skipped"]
    assert len(skipped) == 1


def test_thin_jd_is_flagged(client: TestClient, db: Session, registered: dict) -> None:
    """FR-J4: warn rather than silently produce a weak interview."""
    response = client.post(
        f"{PREFIX}/jds",
        json={"title": "Vague role", "text": "We want a rockstar ninja who ships fast. " * 3},
    )
    version_id = uuid.UUID(response.json()["id"])
    parse_jd_version(db, version_id)
    db.flush()

    version = db.get(JDVersion, version_id)
    assert version is not None
    assert version.thin is True


def _start_session(client: TestClient, db: Session) -> tuple[str, dict]:
    jd_version_id = _create_jd(client, db)
    session_id = client.post(
        f"{PREFIX}/sessions",
        json={
            "mode": "jd",
            "seniority": "senior",
            "target_minutes": 30,
            "jd_version_id": str(jd_version_id),
        },
    ).json()["session"]["id"]
    client.post(
        f"{PREFIX}/sessions/{session_id}/consent",
        json={
            "accepts_ai_assessment": True,
            "accepts_recording": True,
            "accepts_retention": True,
        },
    )
    return session_id, client.post(f"{PREFIX}/sessions/{session_id}/start").json()


SPOKEN = (
    "It has to walk past all those rows first and throw them away, so the deeper you page "
    "the slower it gets. The fix is to remember where you stopped and start there next time."
)


def test_a_spoken_answer_stores_its_timeline(
    client: TestClient, db: Session, registered: dict
) -> None:
    """FR-V2/V3: the segments and their timings survive the round trip."""
    session_id, turn = _start_session(client, db)

    client.post(
        f"{PREFIX}/sessions/{session_id}/answers",
        json={
            "question_id": turn["question_id"],
            "transcript": SPOKEN,
            "input_mode": "speech",
            "duration_ms": 14_000,
            "segments": [
                {"text": "It has to walk past all those rows first", "start_ms": 0,
                 "end_ms": 4200, "confidence": 0.93},
                {"text": "and throw them away", "start_ms": 4200,
                 "end_ms": 6000, "confidence": 0.88},
            ],
            "idempotency_key": f"key-{uuid.uuid4().hex}",
        },
    )

    interview = db.get(InterviewSession, uuid.UUID(session_id))
    assert interview is not None
    db.refresh(interview)
    answers = [a for q in interview.questions for a in q.answers if a.transcript]
    assert len(answers) == 1
    answer = answers[0]
    assert answer.input_mode == "speech"
    assert [segment.ordinal for segment in answer.segments] == [0, 1]
    assert answer.segments[0].start_ms == 0
    assert answer.segments[1].end_ms == 6000
    assert all(not segment.low_confidence for segment in answer.segments)


def test_the_server_decides_what_counts_as_low_confidence(
    client: TestClient, db: Session, registered: dict
) -> None:
    """FR-V4: uncertainty is marked, and the client does not get a vote.

    A client that could set ``low_confidence`` itself could launder a bad
    transcription as a certain one -- so the flag is not in the request schema
    at all, and the threshold lives in server config.
    """
    session_id, turn = _start_session(client, db)

    response = client.post(
        f"{PREFIX}/sessions/{session_id}/answers",
        json={
            "question_id": turn["question_id"],
            "transcript": SPOKEN,
            "input_mode": "speech",
            "duration_ms": 9000,
            "segments": [
                # Below the threshold, and *claiming* to be certain.
                {"text": "I did potent", "start_ms": 0, "end_ms": 900, "confidence": 0.21,
                 "low_confidence": False},
            ],
            "idempotency_key": f"key-{uuid.uuid4().hex}",
        },
    )
    # `extra="forbid"`: the client cannot even name the field.
    assert response.status_code == 422

    client.post(
        f"{PREFIX}/sessions/{session_id}/answers",
        json={
            "question_id": turn["question_id"],
            "transcript": SPOKEN,
            "input_mode": "speech",
            "duration_ms": 9000,
            "segments": [
                {"text": "I did potent", "start_ms": 0, "end_ms": 900, "confidence": 0.21},
                {"text": "so the deeper you page the slower it gets", "start_ms": 900,
                 "end_ms": 3000, "confidence": 0.95},
                # No confidence reported at all is not the same as low confidence.
                {"text": "remember where you stopped", "start_ms": 3000, "end_ms": 5000,
                 "confidence": None},
            ],
            "idempotency_key": f"key-{uuid.uuid4().hex}",
        },
    )

    interview = db.get(InterviewSession, uuid.UUID(session_id))
    assert interview is not None
    db.refresh(interview)
    answer = next(a for q in interview.questions for a in q.answers if a.transcript)
    assert [segment.low_confidence for segment in answer.segments] == [True, False, False]


def test_a_backwards_span_is_clamped_not_stored(
    client: TestClient, db: Session, registered: dict
) -> None:
    """A recogniser reporting end before start is a bug in the recogniser.

    Storing it would put an unplottable range on the timeline HR jumps around
    with (FR-H4), so the seam refuses to persist one.
    """
    session_id, turn = _start_session(client, db)

    client.post(
        f"{PREFIX}/sessions/{session_id}/answers",
        json={
            "question_id": turn["question_id"],
            "transcript": SPOKEN,
            "input_mode": "speech",
            "duration_ms": 5000,
            "segments": [{"text": "backwards", "start_ms": 4000, "end_ms": 100,
                          "confidence": 0.9}],
            "idempotency_key": f"key-{uuid.uuid4().hex}",
        },
    )

    interview = db.get(InterviewSession, uuid.UUID(session_id))
    assert interview is not None
    db.refresh(interview)
    answer = next(a for q in interview.questions for a in q.answers if a.transcript)
    assert answer.segments[0].end_ms >= answer.segments[0].start_ms


def test_a_typed_answer_has_no_timeline_and_no_stt_cost(
    client: TestClient, db: Session, registered: dict
) -> None:
    """The two modes are the same path, and the records say which one ran."""
    from app.domain.enums import CostKind
    from app.models.ops import UsageCost

    session_id, turn = _start_session(client, db)
    client.post(
        f"{PREFIX}/sessions/{session_id}/answers",
        json={
            "question_id": turn["question_id"],
            "transcript": SPOKEN,
            "idempotency_key": f"key-{uuid.uuid4().hex}",
        },
    )

    interview = db.get(InterviewSession, uuid.UUID(session_id))
    assert interview is not None
    db.refresh(interview)
    answer = next(a for q in interview.questions for a in q.answers if a.transcript)
    assert answer.input_mode == "typed"
    assert answer.segments == []

    stt = (
        db.query(UsageCost)
        .filter(UsageCost.session_id == interview.id, UsageCost.kind == CostKind.STT_SECONDS)
        .all()
    )
    assert stt == [], "typing costs no STT seconds, and the ledger should say so by omission"


def test_an_untouched_core_concept_earns_a_followup_not_a_silent_miss(
    client: TestClient, db: Session, registered: dict
) -> None:
    """FR-E5a: nothing is reported missing that was never asked about.

    The complaint this encodes came from a real report: four of five concepts
    covered, the fifth marked `missing` having never been put to the candidate.
    A real interviewer would have followed up, so now so do we -- and because
    the follow-up uses the concept's authored signpost (L2 hint content), it is
    recorded as a hint so the credit discount is honest.
    """
    from app.models.interview import Hint

    session_id, turn = _start_session(client, db)

    # A long answer, so the word-count backstop cannot be what fires. It is
    # firmly on topic and deliberately does not reach every core concept.
    response = client.post(
        f"{PREFIX}/sessions/{session_id}/answers",
        json={
            "question_id": turn["question_id"],
            "transcript": (
                "I would think carefully about the overall shape of the system and how the "
                "pieces fit together, considering the various trade-offs involved and what "
                "the team already knows, because context matters more than any single rule "
                "of thumb people like to repeat in these conversations."
            ),
            "idempotency_key": f"key-{uuid.uuid4().hex}",
        },
    ).json()

    next_turn = response["next_turn"]
    assert next_turn["question_id"] == turn["question_id"], "follow-ups stay on the question"
    assert next_turn["is_followup"] is True
    prompt = next_turn["followup_prompt"]
    assert prompt

    interview = db.get(InterviewSession, uuid.UUID(session_id))
    assert interview is not None
    db.refresh(interview)
    question = next(q for q in interview.questions if str(q.id) == turn["question_id"])

    hints = db.query(Hint).filter(Hint.session_question_id == question.id).all()
    if any(hint.trigger == "uncovered" for hint in hints):
        # Signposted: the discount must be recorded against that concept alone.
        hint = next(hint for hint in hints if hint.trigger == "uncovered")
        assert hint.touched_concept_ids, "a signposted concept must be named in the audit row"
        discounted = [c.concept_id for c in question.concepts if c.hint_touched]
        assert set(hint.touched_concept_ids) <= set(discounted)
        assert "counts as a hint" in prompt, "FR-E4f: never a silent penalty"
        # The ladder is the candidate's to spend; noticing a gap must not empty it.
        assert question.hint_count == 0


def test_a_complete_answer_is_not_followed_up(
    client: TestClient, db: Session, registered: dict
) -> None:
    """The other half: a follow-up on every question would just be padding."""
    session_id, turn = _start_session(client, db)

    interview = db.get(InterviewSession, uuid.UUID(session_id))
    assert interview is not None
    db.refresh(interview)
    question = next(q for q in interview.questions if str(q.id) == turn["question_id"])
    # Answer using the rubric's own plain-language signals, which is what a
    # candidate who understands the topic would say in their own words.
    spoken = " ".join(
        signal
        for concept in question.concepts
        for signal in (concept.acceptable_signals or [])[:3]
    )

    response = client.post(
        f"{PREFIX}/sessions/{session_id}/answers",
        json={
            "question_id": turn["question_id"],
            "transcript": spoken,
            "idempotency_key": f"key-{uuid.uuid4().hex}",
        },
    ).json()

    next_turn = response.get("next_turn")
    if next_turn is not None:
        assert next_turn["is_followup"] is False, "a covered answer needs no nudge"


def test_a_question_with_a_followup_can_still_reach_published(
    client: TestClient, db: Session, registered: dict
) -> None:
    """The bug that left every dashboard row saying "Grading…" forever.

    A follow-up is a second *turn* on the same question, and grading reads the
    combined transcript, so a question yields one evaluation no matter how many
    turns it took. `publish_session_task` used to demand an evaluation per
    turn, which no question with a follow-up could ever satisfy -- the session
    stayed at `completed`, the outbox burned its eight attempts, and the event
    died `failed`.
    """
    from app.services.grading import publish_session

    session_id, turn = _start_session(client, db)

    # Answer every question thinly, so each one earns a follow-up, then answer
    # the follow-up too. Two turns per question, one evaluation per question.
    current: dict | None = turn
    guard = 0
    while current and guard < 30:
        guard += 1
        body = client.post(
            f"{PREFIX}/sessions/{session_id}/answers",
            json={
                "question_id": current["question_id"],
                "transcript": SPOKEN,
                "idempotency_key": f"key-{uuid.uuid4().hex}",
            },
        ).json()
        if body.get("session_completed"):
            break
        current = body.get("next_turn")

    interview = db.get(InterviewSession, uuid.UUID(session_id))
    assert interview is not None
    db.refresh(interview)
    turns = [a for q in interview.questions for a in q.answers if a.transcript]
    assert len(turns) > len(interview.questions), "the test needs follow-ups to have happened"

    for question in interview.questions:
        for answer in question.answers:
            if answer.transcript:
                grade_answer(db, answer_id=answer.id)
    db.flush()

    # Publishing must not care that some turns have no evaluation of their own.
    assert publish_session(db, session_id=interview.id) in {"graded", "published"}
    # No `db.refresh` here: publish_session stages the transition and the seam
    # commits it, so refreshing would reload the pre-flush row and hide the
    # very change being asserted.
    db.flush()
    assert interview.status == SessionStatus.PUBLISHED


def test_publishing_waits_while_a_question_is_genuinely_ungraded(
    client: TestClient, db: Session, registered: dict
) -> None:
    """The other half: don't publish a report with a hole in it."""
    from app.services.grading import publish_session

    session_id, turn = _start_session(client, db)
    current: dict | None = turn
    guard = 0
    while current and guard < 30:
        guard += 1
        body = client.post(
            f"{PREFIX}/sessions/{session_id}/answers",
            json={
                "question_id": current["question_id"],
                "transcript": SPOKEN,
                "idempotency_key": f"key-{uuid.uuid4().hex}",
            },
        ).json()
        if body.get("session_completed"):
            break
        current = body.get("next_turn")

    interview = db.get(InterviewSession, uuid.UUID(session_id))
    assert interview is not None
    db.refresh(interview)
    # Nothing graded at all: it must refuse, and the relay keeps the event.
    with pytest.raises(RuntimeError, match="awaiting a verdict"):
        publish_session(db, session_id=interview.id)
    assert interview.status == SessionStatus.COMPLETED
