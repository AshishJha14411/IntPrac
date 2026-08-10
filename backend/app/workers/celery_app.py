"""Celery application.

**Bulkheads (NFR-S5).** Grading, parsing, and media get separate queues, so a
media backlog can never starve grading and vice versa. That is the whole point
of routing here rather than dumping everything on ``celery``.

**Two dispatch modes (ADR 010).** With a worker running, this is an ordinary
Celery app. With ``CELERY_TASK_ALWAYS_EAGER=true`` there is no worker and no
broker traffic at all -- see the block at the bottom of this file, and read the
warning there before assuming the flag is sufficient on its own.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings
from app.core.logging import configure_logging

configure_logging()

celery_app = Celery(
    "interview",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.tasks.grading",
        "app.workers.tasks.parsing",
        "app.workers.tasks.outbox",
        "app.workers.tasks.retention",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # At-least-once: ack after the task finishes, so a worker killed mid-task
    # redelivers instead of silently dropping the job. Safe precisely because
    # the consumers are idempotent (NFR-S6).
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="grading",
    task_routes={
        "app.workers.tasks.grading.*": {"queue": "grading"},
        "app.workers.tasks.parsing.*": {"queue": "parsing"},
        "app.workers.tasks.outbox.*": {"queue": "grading"},
        "app.workers.tasks.retention.*": {"queue": "media"},
    },
    beat_schedule={
        # The outbox relay. Frequent because grading latency is user-visible.
        "drain-outbox": {
            "task": "app.workers.tasks.outbox.drain_outbox",
            "schedule": 5.0,
        },
        # NFR-P: retention is a job, not a promise.
        "apply-retention": {
            "task": "app.workers.tasks.retention.apply_retention",
            "schedule": crontab(hour=3, minute=17),
        },
    },
)


# ---------------------------------------------------------------------------
# WORKERLESS MODE (ADR 010)
# ---------------------------------------------------------------------------
# ``task_always_eager`` makes ``.delay()`` run the task inline in the calling
# process, so no worker is needed.
#
# ``task_eager_propagates=False`` is the half that matters. Left True (the test
# default) a failing task raises straight into whatever called ``.delay()`` --
# a transient Anthropic 529 would turn a successfully-saved answer into a 500.
# False keeps the failure inside the result: the write already succeeded, the
# event stays pending, and the relay retries it. Degrade, don't explode.
#
# ⚠ THIS FLAG ALONE IS NOT ENOUGH IN THIS CODEBASE, and that is the one real
# difference from the v1 blog project it was borrowed from. There, every call
# site calls ``.delay()`` directly, so eager mode is a complete answer. Here,
# writes stage a *transactional outbox row* and the only thing that turns rows
# into ``.delay()`` calls is ``drain_outbox``, which runs on Celery **beat** --
# a second always-on process, and the very thing we are trying not to pay for.
# Set this flag on its own and every event would sit at ``pending`` forever
# while the API returned 200s. ``app/services/dispatch.py`` supplies the
# missing half: the request drains the outbox itself once its transaction has
# committed.
if settings.celery_task_always_eager:
    celery_app.conf.update(
        task_always_eager=True,
        task_eager_propagates=False,
    )
