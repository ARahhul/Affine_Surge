"""Dependency injection providers for the CT200 QA Traceability System.

All service dependencies are provided via FastAPI's Depends() mechanism.
No service class directly instantiates its own repository or external client.

Usage in routers:
    from fastapi import Depends
    from ct200.dependencies import get_cached_settings

    @router.get("/example")
    async def example(settings: Settings = Depends(get_cached_settings)):
        ...
"""

from functools import lru_cache

from ct200.config import Settings, get_settings


@lru_cache
def get_cached_settings() -> Settings:
    """Cached settings instance — loaded once at startup.

    Uses lru_cache so the Settings object is created exactly once
    and reused across all requests.
    """
    return get_settings()
