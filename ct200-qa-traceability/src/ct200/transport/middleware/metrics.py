"""Prometheus metrics middleware for request instrumentation.

Records per-endpoint request counts, latency histograms, and error counts
for all HTTP requests flowing through the application.
"""

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from ct200.transport.routers.health import REQUEST_COUNT, REQUEST_LATENCY, ERROR_COUNT


class MetricsMiddleware(BaseHTTPMiddleware):
    """Instruments every request with Prometheus metrics.

    Metrics recorded:
    - http_requests_total: Counter with labels (method, endpoint, status_code)
    - http_request_duration_seconds: Histogram with labels (method, endpoint)
    - http_errors_total: Counter for 4xx/5xx with labels (method, endpoint, status_code)
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        method = request.method
        path = request.url.path

        start_time = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start_time

        status_code = str(response.status_code)

        REQUEST_COUNT.labels(
            method=method, endpoint=path, status_code=status_code
        ).inc()
        REQUEST_LATENCY.labels(method=method, endpoint=path).observe(duration)

        if response.status_code >= 400:
            ERROR_COUNT.labels(
                method=method, endpoint=path, status_code=status_code
            ).inc()

        return response
