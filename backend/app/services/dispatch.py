"""Where background work gets handed off -- and, in workerless mode, run.

Read ADR 010 first. The short version: a Celery worker is a polling consumer,
so a scale-to-zero host has to pin it to one always-on instance, and that CPU
is billed around the clock whether or not a single task runs. On a self-funded
deployment that is the entire bill (§8.3: cost is a design constraint, not a
metric). Setting ``CELERY_TASK_ALWAYS_EAGER=true`` deletes the worker.

The catch this module exists to close: eager mode only changes what ``.delay()``
does. Writes here don't call ``.delay()`` -- they stage an outbox row, and the
relay that turns rows into ``.delay()`` calls runs on Celery **beat**, which is
a second always-on process. Deleting the worker without replacing the relay
gives you an API that returns 200 while nothing is ever graded.

So the request itself drains the outbox, once its own transaction has committed.

**Why after the commit and not after the response.** FastAPI's
``BackgroundTasks`` and Starlette's post-response hooks would keep the request
fast, and on a scale-to-zero host they would also quietly not work: CPU is
allocated *in response to a request*, so work scheduled after the response is
throttled to near-nothing and dies when the instance is reclaimed. Work has to
happen while the request is still open. That is the trade, and it is the reason
the drain is awaited rather than fired and forgotten.
"""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def dispatch_mode() -> str:
    """``"inline"`` or ``"worker"`` -- surfaced on ``/health/ready``.

    Whether a worker exists is deployment state, invisible from the repo. The
    v1 project learned this the expensive way: the flag lived only in a console,
    so "are tasks actually running in production?" could not be answered without
    opening it. Reporting the mode the process is *actually* in makes that a
    curl away.
    """
    return "inline" if settings.workerless else "worker"


async def drain_after_commit() -> None:
    """Drain the outbox in-process. A no-op unless we are running workerless.

    Never raises. The caller's transaction has already committed by the time
    this runs, so an exception here could only turn a successful write into a
    500 -- the same failure mode ``task_eager_propagates=False`` exists to
    prevent, one layer up.
    """
    if not settings.inline_dispatch_enabled:
        return

    # Imported lazily: `app.db.session` imports this module, and the relay
    # imports `app.db.session`.
    from app.workers.tasks.outbox import drain_outbox

    try:
        # The relay is sync (it shares the worker's engine, by design -- see
        # Appendix D.4). Running it on the event loop would block every other
        # request on this instance for the length of an LLM call.
        await run_in_threadpool(
            drain_outbox,
            batch_size=settings.inline_drain_batch_size,
            budget_seconds=settings.inline_drain_budget_seconds,
        )
    except Exception as exc:  # pragma: no cover - defensive; the relay handles its own
        logger.warning("inline_drain_failed", error=str(exc))
