"""FastAPI application factory for the CT200 QA Traceability System."""

from fastapi import FastAPI

from ct200.config import get_settings
from ct200.infrastructure.logging import configure_logging
from ct200.transport.middleware.correlation import CorrelationMiddleware
from ct200.transport.middleware.error_handler import ErrorHandlerMiddleware
from ct200.transport.middleware.metrics import MetricsMiddleware


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Middleware stack order (outermost first):
    1. CorrelationMiddleware — injects X-Correlation-ID
    2. ErrorHandlerMiddleware — catches exceptions, returns structured JSON
    3. MetricsMiddleware — Prometheus counter/histogram instrumentation

    Auth and rate limiting middleware will be added in Phase 4 (Tasks 7.5, 7.6).
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

    # Middleware stack — order matters (last added = outermost)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(ErrorHandlerMiddleware)
    app.add_middleware(CorrelationMiddleware)

    # Register routers
    from ct200.transport.routers.health import router as health_router

    app.include_router(health_router)

    return app


# Application instance for uvicorn
app = create_app()
