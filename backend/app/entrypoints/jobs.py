"""Run a scheduled job once, then exit.

Beat is a second always-on process, so workerless mode (ADR 010) deletes it
along with the worker -- and that would quietly take the retention job with it.
"Retention is a job, not a promise" (NFR-P) stops being true the moment nothing
runs it, and this app holds video, voice and resumes.

So the scheduled work gets an entrypoint that any *external* scheduler can
invoke, none of which needs a process sitting idle:

    docker compose run --rm --no-deps api python -m app.entrypoints.jobs retention

Cloud Run Jobs + Cloud Scheduler, a GitHub Actions ``schedule:``, or plain cron
all drive this the same way and all cost nothing while it isn't running. With a
worker deployed, beat already covers it and this is just a manual handle.
"""

from __future__ import annotations

import sys

from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


def _retention() -> object:
    from app.workers.tasks.retention import apply_retention

    return apply_retention()


def _drain() -> object:
    from app.workers.tasks.outbox import drain_outbox

    # No budget: nothing is waiting on this process, so it may as well finish
    # the backlog rather than hand it to the next request.
    return drain_outbox(batch_size=200)


JOBS = {"retention": _retention, "drain": _drain}


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = argv if argv is not None else sys.argv[1:]
    name = args[0] if args else ""
    job = JOBS.get(name)
    if job is None:
        print(f"usage: python -m app.entrypoints.jobs {{{'|'.join(JOBS)}}}", file=sys.stderr)
        return 2
    result = job()
    logger.info("job_finished", job=name, result=result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
