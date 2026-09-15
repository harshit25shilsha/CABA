"""
Alembic environment.

Deliberately does NOT read sqlalchemy.url from alembic.ini — the URL and
target schema both come from the application itself, so migrations are
always generated/applied against the same config the app runs with.
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make `app` importable when Alembic is invoked from the project root
# (`alembic revision ...` / `alembic upgrade ...`).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.models import Base  # noqa: E402  (imports every model so Base.metadata is complete)

config = context.config

# Inject the real DB URL from Settings instead of alembic.ini's placeholder.
# Always the SYNC uri (psycopg2) — asyncpg has no sync driver for Alembic to use.
config.set_main_option("sqlalchemy.url", settings.SQLALCHEMY_SYNC_URI)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The single source of truth for autogenerate — every model in app/models/
# is registered on this metadata via app/models/__init__.py.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection (`alembic upgrade --sql`)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Standard path — connect and run migrations against the real DB."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Catches column type changes and dropped server defaults that
            # autogenerate misses by default — both matter once JSONB/Enum
            # columns start evolving.
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()