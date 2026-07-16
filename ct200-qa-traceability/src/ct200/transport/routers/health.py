"""Health, readiness, and metrics endpoints.

Provides:
- GET /health — liveness probe (always 200 if process is alive)
- GET /ready — readiness probe (200 if DB reachable within 5s, 503 otherwise)
- GET /metrics — Prometheus-format metrics
"""

from fastapi import APIRouter, Response
from prometheus_client import (
    Counter,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
    REGISTRY,
)
from sqlalchemy import text

import structlog

logger = structlog.get_logger()

router = APIRouter(tags=["health"])

# Prometheus metrics — used by both this module and MetricsMiddleware
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)
ERROR_COUNT = Counter(
    "http_errors_total",
    "Total HTTP errors (4xx and 5xx)",
    ["method", "endpoint", "status_code"],
)


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe — returns 200 if the process is alive."""
    return {"status": "healthy"}


@router.get("/ready")
async def ready() -> Response:
    """Readiness probe — checks DB connectivity with a 5-second timeout.

    Returns HTTP 200 if a lightweight DB query succeeds, HTTP 503 otherwise.
    """
    from ct200.infrastructure.database.engine import get_engine

    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return Response(
            content='{"status": "ready"}',
            status_code=200,
            media_type="application/json",
        )
    except Exception as exc:
        logger.warning("readiness_check_failed", error=str(exc))
        return Response(
            content='{"status": "not_ready", "reason": "database_unavailable"}',
            status_code=503,
            media_type="application/json",
        )


@router.get("/metrics")
async def metrics() -> Response:
    """Prometheus metrics endpoint — returns all registered metrics."""
    return Response(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
    )
