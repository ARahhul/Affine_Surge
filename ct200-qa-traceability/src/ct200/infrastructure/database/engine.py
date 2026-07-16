"""SQLAlchemy async engine and session factory for SQLite with WAL mode."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ct200.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Get or create the async SQLAlchemy engine.

    Configures SQLite with aiosqlite driver, WAL mode, and FK enforcement.
    WAL mode and foreign keys are set via event listener in models.py.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        # Convert sqlite:/// to sqlite+aiosqlite:/// for async support
        if url.startswith("sqlite:///"):
            url = url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)

        _engine = create_async_engine(
            url,
            echo=False,
            connect_args={"timeout": 5},
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the async session factory."""
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        _session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a new async session. Use as dependency in FastAPI."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


def reset_engine() -> None:
    """Reset engine and session factory (for testing)."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None
