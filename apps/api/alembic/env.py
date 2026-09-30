"""
Alembic environment for Phase 1 database migrations.

This file:
1. Imports all Phase 1 models so Alembic auto-detects table changes
2. Uses DATABASE_URL_SYNC from config (psycopg2 / sync driver)
3. Supports both offline and online migration modes

To generate a new migration after changing models:
  cd apps/api
  .venv\Scripts\alembic revision --autogenerate -m "description"

To apply all pending migrations:
  .venv\Scripts\alembic upgrade head

To roll back one migration:
  .venv\Scripts\alembic downgrade -1
"""
from __future__ import annotations

import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Make app modules importable from alembic context
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import config first (reads .env)
from core.config import settings

# Import ALL Phase 1 models so Alembic sees them
import models  # noqa: F401 — registers AgentRun, ApprovalRequest with Base.metadata

from core.database import Base

# Alembic Config object
config = context.config

# Override sqlalchemy.url with the value from our Settings object
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL_SYNC)

# Set up logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live database connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
