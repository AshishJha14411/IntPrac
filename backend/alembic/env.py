"""Alembic environment.

⚠ The near-miss this file is written to prevent: a local ``docker compose``
migration once ran against **production** because ``MIGRATION_DATABASE_URL``
fell through to the prod value in ``.env``. So: the URL is read from one
explicit variable, it is printed at startup with credentials masked, and every
compose service that can run migrations pins it (Appendix D.3).
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _mask(url: str) -> str:
    if "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    _creds, host = rest.split("@", 1)
    return f"{scheme}://***@{host}"


def _url() -> str:
    url = settings.migration_database_url
    if not url:
        raise RuntimeError("MIGRATION_DATABASE_URL is not set. Refusing to guess a target.")
    print(f"[alembic] target: {_mask(url)}", file=sys.stderr)
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
