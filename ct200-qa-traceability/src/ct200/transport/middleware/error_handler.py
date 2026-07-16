"""Global exception handler mapping domain exceptions to structured JSON responses."""

from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from ct200.domain.exceptions import CT200Error


def _build_error_response(
    error: CT200Error,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Build the standard error response envelope."""
    return {
        "error": {
            "code": error.code,
            "message": error.message,
            "details": error.details,
            "correlation_id": correlation_id or "unknown",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    }


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """Catches unhandled exceptions and returns structured JSON error responses."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        correlation_id: str | None = getattr(request.state, "correlation_id", None)
        try:
            return await call_next(request)
        except CT200Error as exc:
            body = _build_error_response(exc, correlation_id)
            return JSONResponse(
                status_code=exc.status_code,
                content=body,
            )
        except Exception:
            # Unexpected errors — log will be handled by structlog elsewhere
            error = CT200Error("An unexpected internal error occurred")
            body = _build_error_response(error, correlation_id)
            return JSONResponse(
                status_code=500,
                content=body,
            )
