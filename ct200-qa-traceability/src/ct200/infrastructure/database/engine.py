"""SQLAlchemy async engine and session factory for SQLite with WAL mode."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ct200.config import get_settings

_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    """Get or create the async SQLAlchemy engine.

    Configures SQLite with aiosqlite driver and a 5-second connection timeout.
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


def reset_engine() -> None:
    """Reset the engine (useful for testing)."""
    global _engine
    _engine = None
