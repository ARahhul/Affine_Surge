"""Middleware to inject and propagate correlation IDs through the request lifecycle.

Injects a unique X-Correlation-ID header into every request/response cycle.
If the incoming request already contains the header, it is preserved.
Otherwise, a new UUID4 is generated.

The correlation ID is:
- Stored on request.state.correlation_id for downstream access
- Bound to structlog contextvars so all log entries within the request carry it
- Returned in the response X-Correlation-ID header
"""

import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

import structlog

CORRELATION_HEADER = "X-Correlation-ID"


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Extracts or generates a correlation ID and binds it to structlog context.

    Ensures every request has a unique correlation ID that propagates through
    the full request lifecycle, appearing in all structured log entries.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Use existing header or generate a new one
        correlation_id = request.headers.get(CORRELATION_HEADER) or str(uuid.uuid4())

        # Store on request state for downstream access (logging, error handler)
        request.state.correlation_id = correlation_id

        # Clear and bind to structlog context for the duration of this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        response = await call_next(request)

        # Echo correlation ID in response headers
        response.headers[CORRELATION_HEADER] = correlation_id

        return response
