"""Authentication middleware — validates bearer tokens on all non-exempt endpoints.

Exempt endpoints: /health, /ready, /metrics, /docs, /redoc, /openapi.json
All other requests require a valid Authorization: Bearer <token> header.
"""

import hmac

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from ct200.config import get_settings

# Endpoints that don't require authentication
EXEMPT_PATHS: set[str] = {
    "/health",
    "/ready",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
}


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates bearer tokens against AUTH_SECRET_KEY.

    Rejects requests without valid credentials on all non-exempt endpoints
    with HTTP 401 and a structured error response (Req 12.1, CP-12.1).
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        # Skip auth for exempt endpoints
        if path in EXEMPT_PATHS or path.startswith("/docs") or path.startswith("/redoc"):
            return await call_next(request)

        # Extract bearer token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return self._unauthorized_response(request)

        token = auth_header[7:]  # Strip "Bearer " prefix
        if not token:
            return self._unauthorized_response(request)

        # Validate token against secret key using constant-time comparison
        settings = get_settings()
        if not hmac.compare_digest(token, settings.auth_secret_key):
            return self._unauthorized_response(request)

        return await call_next(request)

    def _unauthorized_response(self, request: Request) -> JSONResponse:
        """Return structured 401 error response."""
        correlation_id = getattr(request.state, "correlation_id", "unknown")
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "code": "AUTH_REQUIRED",
                    "message": "Valid authentication credentials are required",
                    "details": {},
                    "correlation_id": correlation_id,
                }
            },
        )
