"""
Shared pytest fixtures for Phase 1 tests.
"""
from __future__ import annotations

import os
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Set test environment BEFORE importing app modules
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_SECRET", "test-secret-for-tests-only-not-production")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("OWNER_EMAIL", "test@example.com")
os.environ.setdefault(
    "OWNER_PASSWORD_HASH",
    # bcrypt hash of "testpassword" — generated with bcrypt 3.x
    "$2b$12$8PODWaXwTyccz1Bv1YXF5O.S1OTokKhTA8B1tQpaYtEB0GGFVmHtG",
)
os.environ.setdefault("NEMOTRON_ENABLED", "false")

# In-memory SQLite engine for tests so all DB-dependent tests can execute cleanly
test_engine = create_async_engine(
    "sqlite+aiosqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def setup_test_database():
    """Create all tables in the SQLite test database for each test."""
    from core.database import Base
    import models  # noqa: F401 Ensure models are registered

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def override_get_db():
    """Dependency override providing an async SQLite test session."""
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.fixture
def app():
    """Return the FastAPI app instance with DB dependency overridden."""
    from main import app as fastapi_app
    from core.database import get_db

    fastapi_app.dependency_overrides[get_db] = override_get_db
    return fastapi_app


@pytest.fixture
async def client(app):
    """Async HTTP client pointing at the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.fixture
def valid_token() -> str:
    """Return a valid JWT for the test owner."""
    from routers.auth import _create_access_token
    token, _ = _create_access_token("test@example.com")
    return token


@pytest.fixture
def auth_headers(valid_token: str) -> dict:
    """Return Authorization headers for authenticated requests."""
    return {"Authorization": f"Bearer {valid_token}"}
