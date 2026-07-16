"""FastAPI application factory for the CT200 QA Traceability System."""

from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded

from ct200.config import get_settings
from ct200.infrastructure.logging import configure_logging
from ct200.transport.middleware.auth import AuthMiddleware
from ct200.transport.middleware.correlation import CorrelationMiddleware
from ct200.transport.middleware.error_handler import ErrorHandlerMiddleware
from ct200.transport.middleware.metrics import MetricsMiddleware
from ct200.transport.middleware.rate_limit import limiter, rate_limit_exceeded_handler


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Middleware stack order (outermost first):
    1. CorrelationMiddleware — injects X-Correlation-ID
    2. AuthMiddleware — validates bearer tokens (skips exempt paths)
    3. ErrorHandlerMiddleware — catches exceptions, returns structured JSON
    4. MetricsMiddleware — Prometheus counter/histogram instrumentation

    Rate limiting is handled via slowapi decorators on individual endpoints,
    with the limiter instance attached to app.state.
    """
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="CT200 QA Traceability System",
        description="Parse CT200 PDFs into versioned document trees and generate QA test cases",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Attach slowapi limiter to app state and register exception handler
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # type: ignore[arg-type]

    # Middleware stack — order matters (last added = outermost)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(ErrorHandlerMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(CorrelationMiddleware)

    # Register routers
    from ct200.transport.routers.browse import router as browse_router
    from ct200.transport.routers.generation import router as generation_router
    from ct200.transport.routers.health import router as health_router
    from ct200.transport.routers.impact import router as impact_router
    from ct200.transport.routers.ingestion import router as ingestion_router
    from ct200.transport.routers.search import router as search_router
    from ct200.transport.routers.selection import router as selection_router

    app.include_router(health_router)
    app.include_router(ingestion_router)
    app.include_router(browse_router)
    app.include_router(search_router)
    app.include_router(selection_router)
    app.include_router(generation_router)
    app.include_router(impact_router)

    return app


# Application instance for uvicorn
app = create_app()
