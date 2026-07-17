"""Integration tests for generation, staleness, and search routes.

Tests the new routes at the HTTP layer. NIM calls are not tested (no API key),
but error handling paths and non-NIM routes are fully exercised.
"""

import json
import uuid

import pytest

from conftest import skip_if_no_pdf


# ===========================================================================
# POST /api/v1/generations — error handling (no NIM key)
# ===========================================================================


def test_generation_missing_selection_404(client):
    """Generation with non-existent selection_id returns 404."""
    resp = client.post(
        "/api/v1/generations",
        json={"selection_id": "nonexistent-selection-id"},
    )
    assert resp.status_code == 404


def test_generation_missing_body_422(client):
    """Generation without required fields returns 422."""
    resp = client.post("/api/v1/generations", json={})
    assert resp.status_code == 422


@skip_if_no_pdf
def test_generation_nim_failure_returns_5xx(client, ingest_v1):
    """Generation with a valid selection but no real NIM key returns 502.

    This tests the error-handling path: the NIM client will fail to connect,
    and the route should return 502 (transient/connection error).
    """
    doc_id = ingest_v1["document_id"]
    version_id = ingest_v1["version_id"]

    # Get nodes
    nodes_resp = client.get(f"/api/v1/documents/{doc_id}/nodes?version=1")
    node_ids = [n["id"] for n in nodes_resp.json()[:2]]

    # Create selection
    sel_resp = client.post(
        "/api/v1/selections",
        json={"version_id": version_id, "node_ids": node_ids, "label": "gen test"},
    )
    assert sel_resp.status_code == 201
    sel_id = sel_resp.json()["id"]

    # Attempt generation — NIM will fail (no valid API key)
    gen_resp = client.post(
        "/api/v1/generations",
        json={"selection_id": sel_id},
    )
    # Should be 502 or 504 (NIM connection failure)
    assert gen_resp.status_code in (502, 504)


# ===========================================================================
# GET /api/v1/generations/{gen_id}
# ===========================================================================


def test_get_generation_not_found(client):
    """Non-existent generation ID returns 404."""
    resp = client.get("/api/v1/generations/nonexistent-gen-id")
    assert resp.status_code == 404


# ===========================================================================
# GET /api/v1/selections/{sel_id}/generations
# ===========================================================================


def test_get_generations_for_selection_not_found(client):
    """Non-existent selection returns 404."""
    resp = client.get("/api/v1/selections/nonexistent-sel-id/generations")
    assert resp.status_code == 404


@skip_if_no_pdf
def test_get_generations_for_selection_empty(client, ingest_v1):
    """Selection with no generations returns empty list."""
    doc_id = ingest_v1["document_id"]
    version_id = ingest_v1["version_id"]

    nodes_resp = client.get(f"/api/v1/documents/{doc_id}/nodes?version=1")
    node_ids = [nodes_resp.json()[0]["id"]]

    sel_resp = client.post(
        "/api/v1/selections",
        json={"version_id": version_id, "node_ids": node_ids, "label": "empty gens"},
    )
    sel_id = sel_resp.json()["id"]

    resp = client.get(f"/api/v1/selections/{sel_id}/generations")
    assert resp.status_code == 200
    assert resp.json() == []


# ===========================================================================
# GET /api/v1/nodes/{node_id}/generations
# ===========================================================================


def test_get_generations_for_node_not_found(client):
    """Non-existent node returns 404."""
    resp = client.get("/api/v1/nodes/nonexistent-node-id/generations")
    assert resp.status_code == 404


@skip_if_no_pdf
def test_get_generations_for_node_empty(client, ingest_v1):
    """Node with no associated generations returns empty list or existing records."""
    doc_id = ingest_v1["document_id"]
    nodes_resp = client.get(f"/api/v1/documents/{doc_id}/nodes?version=1")
    node_id = nodes_resp.json()[0]["id"]

    resp = client.get(f"/api/v1/nodes/{node_id}/generations")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ===========================================================================
# GET /api/v1/generations/{gen_id}/staleness
# ===========================================================================


def test_staleness_not_found(client):
    """Non-existent generation returns 404."""
    resp = client.get("/api/v1/generations/nonexistent-gen-id/staleness")
    assert resp.status_code == 404


# ===========================================================================
# GET /api/v1/documents/{doc_id}/search?q=
# ===========================================================================


def test_search_missing_query_422(client):
    """Search without query parameter returns 422."""
    resp = client.get("/api/v1/documents/some-doc/search")
    assert resp.status_code == 422


def test_search_nonexistent_doc_404(client):
    """Search on non-existent document returns 404."""
    resp = client.get("/api/v1/documents/nonexistent-doc/search?q=test")
    assert resp.status_code == 404


@skip_if_no_pdf
def test_search_returns_results(client, ingest_v1):
    """FTS5 search returns matching nodes (if FTS is populated)."""
    doc_id = ingest_v1["document_id"]
    # Search for a term likely in the CT200 manual
    resp = client.get(f"/api/v1/documents/{doc_id}/search?q=safety")
    # May return 200 with empty list if FTS index isn't populated during ingest
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
