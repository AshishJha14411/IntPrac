"""Test harness.

Isolation strategy (Appendix D.5): a **private schema per session** plus a
connection-level transaction with a SAVEPOINT rolled back after each test. No
test can see another's rows, and nothing needs truncating between tests.

See the ``engine`` fixture for the ``search_path`` trap and why the schema is
pinned in ``connect_args`` rather than set in a ``connect`` event.

The other trick worth knowing is ``_SyncToAsyncSession``: it presents the sync
test session behind the async API, so async endpoints run *inside* the test
transaction. No second engine, no lost isolation. This is the single thing that
made the async code testable at all.

⚠ **What this harness cannot catch.** Because the adapter is backed by a *sync*
session, there is no greenlet boundary -- so lazy relationship IO that raises
``MissingGreenlet`` against the real async engine works fine here. Two such
bugs shipped past a green suite during development and were only caught by
running the stack for real. ``scripts/smoke.sh`` exists for exactly that, and
it is not optional before merging anything that touches the async request path.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("LLM_ENABLED", "false")

from app.content.bank_backend import QUESTIONS as BACKEND_QUESTIONS
from app.content.bank_databases import QUESTIONS as DATABASE_QUESTIONS
from app.content.seed import _seed_questions, _seed_taxonomy
from app.core.config import settings
from app.core.shutdown import drain_guard
from app.db.base import Base
from app.db.session import get_session
from app.main import create_app

ALL_QUESTIONS = (*DATABASE_QUESTIONS, *BACKEND_QUESTIONS)
TEST_SCHEMA = f"test_{uuid.uuid4().hex[:10]}"


@pytest.fixture(scope="session")
def engine() -> Iterator[Any]:
    """A private schema for this pytest session, on every connection.

    ⚠ Two layers of the same trap:

    1. ``search_path`` is **per connection**, so setting it once on one
       connection isolates only that connection. Every later pool checkout --
       including the ones the real-thread concurrency tests open -- silently
       lands in ``public``.
    2. Less obviously: doing it as ``SET search_path`` inside a ``connect``
       event **does not stick**. The statement runs inside the connection's
       implicit transaction, and SQLAlchemy rolls that back when the connection
       returns to the pool, quietly reverting it. Tests then pass while writing
       to ``public``, which looks fine until two runs collide or a fixture sees
       another run's rows.

    So the schema is pinned in ``connect_args`` at the protocol level, where no
    rollback can touch it. ``test_isolation.py`` asserts this actually holds
    rather than trusting it.
    """
    # The schema has to exist before any connection pins itself to it.
    bootstrap = create_engine(settings.sync_database_url, future=True)
    with bootstrap.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{TEST_SCHEMA}"'))
    bootstrap.dispose()

    engine = create_engine(
        settings.sync_database_url,
        future=True,
        connect_args={"options": f"-csearch_path={TEST_SCHEMA},public"},
    )
    Base.metadata.create_all(engine)

    yield engine

    engine.dispose()
    teardown = create_engine(settings.sync_database_url, future=True)
    with teardown.begin() as connection:
        connection.execute(text(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE'))
    teardown.dispose()


@pytest.fixture(scope="session")
def seeded(engine: Any) -> None:
    """Load the real taxonomy and bank once. Tests grade against real rubrics."""
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        _seed_taxonomy(session)
        _seed_questions(session)
        session.commit()


@pytest.fixture()
def db(engine: Any, seeded: None) -> Iterator[Session]:
    """A session inside a transaction that is rolled back after the test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


class _SyncToAsyncSession:
    """Present the sync test session behind the async API.

    Async endpoints then execute inside the *test* transaction, so their writes
    roll back with everything else. The alternative -- a second async engine --
    means a second connection, which means the endpoint's writes are invisible
    to the test and vice versa.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        return self._session.execute(*args, **kwargs)

    async def scalars(self, *args: Any, **kwargs: Any) -> Any:
        return self._session.scalars(*args, **kwargs)

    async def get(self, *args: Any, **kwargs: Any) -> Any:
        return self._session.get(*args, **kwargs)

    async def flush(self, *args: Any, **kwargs: Any) -> None:
        self._session.flush(*args, **kwargs)

    async def commit(self) -> None:
        # The savepoint is what gets rolled back; committing here would only
        # release it, which is exactly the semantics we want in a test.
        self._session.flush()

    async def rollback(self) -> None:
        self._session.rollback()

    async def refresh(self, *args: Any, **kwargs: Any) -> None:
        self._session.refresh(*args, **kwargs)

    async def delete(self, instance: Any) -> None:
        self._session.delete(instance)

    async def close(self) -> None:
        return None


@pytest.fixture()
def app(db: Session) -> Any:
    # The drain guard is a module-level singleton because in production one
    # process serves one app. Tests build many, and each teardown drains the
    # shared guard, so reset it per test.
    drain_guard.reset()
    application = create_app()

    async def _override() -> AsyncIterator[Any]:
        """Mirror the real seam, don't replace it.

        ⚠ Overriding ``get_session`` with a bare ``yield session`` throws away
        the unit of work: nothing flushes at the end of the request, so the
        last mutation of every handler is silently lost and only the writes
        that happened to be flushed mid-handler survive. Tests then pass or
        fail based on where the flushes landed. The override has to keep the
        commit-on-success / rollback-on-exception contract.

        Each request also gets its **own nested savepoint**. Without that, a
        request that fails (any 4xx raised as an exception) rolls the session
        back to the single test-wide savepoint and destroys the writes of every
        *earlier* request in the same test -- which is nothing like production,
        where each request owns its own transaction.
        """
        nested = db.begin_nested()
        adapter = _SyncToAsyncSession(db)
        try:
            yield adapter
            db.flush()
            nested.commit()
        except Exception:
            if nested.is_active:
                nested.rollback()
            raise

    application.dependency_overrides[get_session] = _override
    return application


@pytest.fixture()
def client(app: Any) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture()
def registered(client: TestClient) -> dict[str, Any]:
    """A registered, signed-in candidate."""
    response = client.post(
        f"{settings.api_v1_prefix}/auth/register",
        json={
            "email": f"user-{uuid.uuid4().hex[:8]}@example.com",
            "password": "a-long-enough-password-1",
            "display_name": "Test Candidate",
        },
    )
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return response.json()


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


def run_async(coro: Any) -> Any:
    """Run a coroutine from a sync test."""
    return asyncio.run(coro)
