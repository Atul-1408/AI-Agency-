"""
Async SQLAlchemy database engine and session management.

IMPORTANT — asyncpg dependency:
  asyncpg requires Microsoft C++ Build Tools to compile on Windows.
  If asyncpg is not installed, the engine is created lazily (only when
  a DB connection is first attempted). The health endpoint reports the
  database as "unavailable" in that case — this is honest behaviour.

  To install asyncpg on Windows:
    1. Install Microsoft C++ Build Tools from https://visualstudio.microsoft.com/visual-cpp-build-tools/
    2. pip install asyncpg
    Or use Docker: docker compose up db (which uses asyncpg inside the container)
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Optional

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


# Lazy engine — created on first use, not at import time.
# This allows the app to start even when asyncpg is not installed.
_engine = None
_session_factory = None


def _get_engine():
    global _engine
    if _engine is None:
        try:
            from sqlalchemy.ext.asyncio import create_async_engine
            from core.config import settings
            _engine = create_async_engine(
                settings.DATABASE_URL,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
                pool_recycle=300,
                echo=False,
            )
        except ModuleNotFoundError as exc:
            if "asyncpg" in str(exc):
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Database unavailable: asyncpg not installed. "
                        "Install Microsoft C++ Build Tools then run: pip install asyncpg. "
                        "See QUICKSTART.md."
                    ),
                ) from exc
            raise
    return _engine


def _get_session_factory():
    global _session_factory
    if _session_factory is None:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
        _session_factory = async_sessionmaker(
            bind=_get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return _session_factory


class AsyncSessionLocal:
    """Context manager that wraps the lazy session factory."""
    def __init__(self):
        self._session = None

    async def __aenter__(self):
        factory = _get_session_factory()
        self._session = factory()
        return self._session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()


async def get_db() -> AsyncGenerator:
    """
    FastAPI dependency: provides a database session per request.
    Commits on success, rolls back on exception, always closes.
    Raises HTTP 503 if asyncpg is not installed.
    """
    try:
        factory = _get_session_factory()
    except ModuleNotFoundError as exc:
        if "asyncpg" in str(exc):
            from fastapi import HTTPException
            raise HTTPException(
                status_code=503,
                detail="Database unavailable: asyncpg not installed. See QUICKSTART.md.",
            ) from exc
        raise

    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
