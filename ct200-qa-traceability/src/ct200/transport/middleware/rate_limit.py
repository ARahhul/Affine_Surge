"""Rate limiting middleware using slowapi.

Enforces configurable per-client rate limits on ingestion and generation
endpoints. Returns HTTP 429 with Retry-After header when limits are exceeded.
"""

import hashlib

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def _key_func(request: Request) -> str:
    """Extract client identifier for rate limiting.

    Uses a hash of the Authorization bearer token if present,
    falls back to remote IP address.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        # Use a hash of the token as the key (don't store raw tokens)
        token = auth_header[7:]
        return hashlib.sha256(token.encode()).hexdigest()[:16]
    return get_remote_address(request)


# Create the limiter instance with per-client key function
limiter = Limiter(key_func=_key_func)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """Custom handler for rate limit exceeded errors.

    Returns HTTP 429 with structured JSON error and Retry-After header.
    """
    correlation_id = getattr(request.state, "correlation_id", "unknown")

    # Extract retry-after from the exception detail
    # slowapi sets retry_after on the exception as seconds until reset
    retry_after = getattr(exc, "retry_after", 60)
    if retry_after is None:
        retry_after = 60

    response = JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "RATE_LIMIT_EXCEEDED",
                "message": f"Rate limit exceeded. Retry after {retry_after} seconds.",
                "details": {"retry_after": retry_after},
                "correlation_id": correlation_id,
            }
        },
    )
    response.headers["Retry-After"] = str(retry_after)
    return response
