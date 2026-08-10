"""Engines and the unit-of-work seam.

Non-negotiable #1 (Appendix D.1): **one transaction per request, owned by the
DB dependency.** Services stage work; the seam decides commit or rollback.
Nothing below ``api/`` calls ``commit()``.

Dual engines on purpose (Appendix D.4): the async engine serves the request
path, the sync engine serves Celery workers and seed scripts. They coexist
fine and keep the worker code boring.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.services import dispatch

async_engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,  # keeps loaded attrs usable after the seam commits
    autoflush=False,
)

sync_engine = create_engine(
    settings.sync_database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,
    future=True,
)

SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: the unit-of-work seam.

    Yields a session, commits on success, rolls back on any exception. This is
    the *only* place the request path commits.
    """
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

    # Workerless mode only (ADR 010) -- a no-op otherwise, and unreachable if
    # the request failed, because the `raise` above skips it. Two deliberate
    # placements: *after* the commit, so the drain can only ever see events
    # that are real; and *after* close, so its connection doesn't stack on top
    # of this request's and double the pool's peak.
    await dispatch.drain_after_commit()


@contextmanager
def sync_session_scope() -> Iterator[Session]:
    """Same contract for workers and scripts."""
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
