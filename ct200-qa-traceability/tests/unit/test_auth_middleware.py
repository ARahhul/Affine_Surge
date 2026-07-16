"""Unit tests for authentication middleware (Req 12.1, CP-12.1)."""

import os

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from ct200.transport.middleware.auth import AuthMiddleware, EXEMPT_PATHS
from ct200.transport.middleware.correlation import CorrelationMiddleware

TEST_SECRET = "test-secret-key-for-auth"


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    """Ensure required env vars are present for settings validation."""
    monkeypatch.setenv("AUTH_SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "fake-key-for-test")


@pytest.fixture
def app() -> FastAPI:
    """Create minimal test app with auth and correlation middleware."""
    test_app = FastAPI()

    # Add a protected endpoint
    @test_app.get("/api/v1/documents")
    async def documents():
        return {"data": []}

    # Add exempt endpoints
    @test_app.get("/health")
    async def health():
        return {"status": "ok"}

    @test_app.get("/ready")
    async def ready():
        return {"status": "ready"}

    @test_app.get("/metrics")
    async def metrics():
        return {"metrics": "ok"}

    # Middleware stack — last added = outermost
    test_app.add_middleware(AuthMiddleware)
    test_app.add_middleware(CorrelationMiddleware)

    return test_app


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    """Create async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_missing_auth_returns_401(client: AsyncClient):
    """Request without Authorization header returns 401."""
    response = await client.get("/api/v1/documents")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "AUTH_REQUIRED"
    assert body["error"]["message"] == "Valid authentication credentials are required"
    assert "correlation_id" in body["error"]


@pytest.mark.asyncio
async def test_invalid_token_returns_401(client: AsyncClient):
    """Request with wrong token returns 401."""
    response = await client.get(
        "/api/v1/documents",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_malformed_auth_header_returns_401(client: AsyncClient):
    """Request with non-Bearer auth scheme returns 401."""
    response = await client.get(
        "/api/v1/documents",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_empty_bearer_token_returns_401(client: AsyncClient):
    """Request with 'Bearer ' but no token value returns 401."""
    response = await client.get(
        "/api/v1/documents",
        headers={"Authorization": "Bearer "},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_valid_token_passes(client: AsyncClient):
    """Request with valid token passes through to endpoint."""
    response = await client.get(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {TEST_SECRET}"},
    )
    assert response.status_code == 200
    assert response.json() == {"data": []}


@pytest.mark.asyncio
async def test_health_exempt_no_auth(client: AsyncClient):
    """/health endpoint does not require authentication."""
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_ready_exempt_no_auth(client: AsyncClient):
    """/ready endpoint does not require authentication."""
    response = await client.get("/ready")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metrics_exempt_no_auth(client: AsyncClient):
    """/metrics endpoint does not require authentication."""
    response = await client.get("/metrics")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_docs_exempt_no_auth(client: AsyncClient):
    """/docs endpoint does not require authentication."""
    response = await client.get("/docs")
    # FastAPI docs returns 200 or redirects
    assert response.status_code in (200, 307)


@pytest.mark.asyncio
async def test_correlation_id_in_error_response(client: AsyncClient):
    """401 error response includes the correlation_id from the request."""
    correlation_id = "test-corr-123"
    response = await client.get(
        "/api/v1/documents",
        headers={"X-Correlation-ID": correlation_id},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["correlation_id"] == correlation_id
