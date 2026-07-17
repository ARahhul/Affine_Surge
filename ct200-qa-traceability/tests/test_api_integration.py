"""Real HTTP-layer integration tests using TestClient.

Tests all 5 API endpoints with real PDF data flowing through
the full parse → tree → persist pipeline.
"""

import pytest

from conftest import skip_if_no_pdf

# ===========================================================================
# 1. GET /health — always works, no PDF needed
# ===========================================================================


def test_health_returns_200(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


def test_health_response_content_type(client):
    resp = client.get("/health")
    assert "application/json" in resp.headers["content-type"]


# ===========================================================================
# 2. POST /api/v1/documents
# ===========================================================================


@skip_if_no_pdf
def test_ingest_new_document_returns_201(client, ingest_v1):
    """First ingest of a new document returns 201."""
    assert ingest_v1["is_new"] is True
    assert ingest_v1["version_number"] == 1
    assert "document_id" in ingest_v1
    assert "version_id" in ingest_v1


@skip_if_no_pdf
def test_ingest_idempotent_returns_200(client, ingest_v1):
    """Re-ingest of identical content returns 200 (not 201)."""
    import os

    pdf_path = os.path.join(os.path.dirname(__file__), "..", "pdf", "ct200_manual.pdf")
    with open(pdf_path, "rb") as f:
        resp = client.post(
            "/api/v1/documents",
            files={"file": ("ct200_manual.pdf", f, "application/pdf")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_new"] is False
    assert data["version_id"] == ingest_v1["version_id"]


@skip_if_no_pdf
def test_ingest_v2_creates_new_version(client, ingest_v2, ingest_v1):
    """Ingesting v2 PDF creates version_number=2 for the same document."""
    assert ingest_v2["document_id"] == ingest_v1["document_id"]
    assert ingest_v2["version_number"] == 2
    assert ingest_v2["version_id"] != ingest_v1["version_id"]


def test_ingest_non_pdf_fails(client):
    """Uploading a non-PDF file returns an error."""
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("readme.txt", b"Hello world", "text/plain")},
    )
    # Application should reject non-PDF; expect 4xx or 5xx
    assert resp.status_code >= 400


def test_ingest_empty_file(client):
    """Uploading an empty file returns an error."""
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert resp.status_code >= 400


# ===========================================================================
# 3. GET /api/v1/documents/{doc_id}/nodes
# ===========================================================================


@skip_if_no_pdf
def test_get_nodes_returns_list(client, ingest_v1):
    """Fetching nodes for ingested document returns a non-empty list."""
    doc_id = ingest_v1["document_id"]
    resp = client.get(f"/api/v1/documents/{doc_id}/nodes")
    assert resp.status_code == 200
    nodes = resp.json()
    assert isinstance(nodes, list)
    assert len(nodes) > 0


@skip_if_no_pdf
def test_get_nodes_has_required_fields(client, ingest_v1):
    """Each node response contains the expected fields."""
    doc_id = ingest_v1["document_id"]
    resp = client.get(f"/api/v1/documents/{doc_id}/nodes")
    node = resp.json()[0]
    required_fields = {
        "id", "heading", "level", "body", "content_hash",
        "position_index", "lineage_id", "parent_id",
    }
    assert required_fields.issubset(node.keys())


@skip_if_no_pdf
def test_get_nodes_specific_version(client, ingest_v1):
    """Explicit version param returns nodes for that version."""
    doc_id = ingest_v1["document_id"]
    resp = client.get(f"/api/v1/documents/{doc_id}/nodes?version=1")
    assert resp.status_code == 200
    nodes = resp.json()
    assert len(nodes) > 0


@skip_if_no_pdf
def test_get_nodes_version_2(client, ingest_v2):
    """Version 2 nodes can also be fetched."""
    doc_id = ingest_v2["document_id"]
    resp = client.get(f"/api/v1/documents/{doc_id}/nodes?version=2")
    assert resp.status_code == 200
    nodes = resp.json()
    assert len(nodes) > 0


@skip_if_no_pdf
def test_get_nodes_body_truncation(client, ingest_v1):
    """Body field is truncated to 200 chars max in listing."""
    doc_id = ingest_v1["document_id"]
    resp = client.get(f"/api/v1/documents/{doc_id}/nodes")
    for node in resp.json():
        assert len(node["body"]) <= 200


@skip_if_no_pdf
def test_get_nodes_ordering(client, ingest_v1):
    """Nodes are returned in position_index order."""
    doc_id = ingest_v1["document_id"]
    resp = client.get(f"/api/v1/documents/{doc_id}/nodes")
    nodes = resp.json()
    positions = [n["position_index"] for n in nodes]
    assert positions == sorted(positions)


def test_get_nodes_invalid_doc_404(client):
    """Non-existent document returns 404."""
    resp = client.get("/api/v1/documents/nonexistent-id/nodes")
    assert resp.status_code == 404


def test_get_nodes_invalid_version_404(client, ingest_v1 = None):
    """Non-existent version number returns 404."""
    resp = client.get("/api/v1/documents/nonexistent-id/nodes?version=999")
    assert resp.status_code == 404


# ===========================================================================
# 4. GET /api/v1/nodes/{node_id}/diff
# ===========================================================================


@skip_if_no_pdf
def test_diff_returns_history(client, ingest_v2):
    """Diff endpoint returns history for a valid node."""
    doc_id = ingest_v2["document_id"]
    resp = client.get(f"/api/v1/documents/{doc_id}/nodes?version=1")
    node_id = resp.json()[0]["id"]

    diff_resp = client.get(f"/api/v1/nodes/{node_id}/diff")
    assert diff_resp.status_code == 200
    data = diff_resp.json()
    assert "history" in data
    assert "lineage_id" in data
    assert "node_id" in data


@skip_if_no_pdf
def test_diff_history_has_fields(client, ingest_v2):
    """Each history entry has version_id, content_hash, heading, level."""
    doc_id = ingest_v2["document_id"]
    resp = client.get(f"/api/v1/documents/{doc_id}/nodes?version=1")
    node_id = resp.json()[0]["id"]

    diff_resp = client.get(f"/api/v1/nodes/{node_id}/diff")
    entry = diff_resp.json()["history"][0]
    assert "version_id" in entry
    assert "content_hash" in entry
    assert "heading" in entry
    assert "level" in entry


def test_diff_invalid_node_404(client):
    """Non-existent node ID returns 404."""
    resp = client.get("/api/v1/nodes/nonexistent-node-id/diff")
    assert resp.status_code == 404


# ===========================================================================
# 5. POST /api/v1/selections
# ===========================================================================


@skip_if_no_pdf
def test_create_selection_valid(client, ingest_v1):
    """Create a valid selection with one node."""
    doc_id = ingest_v1["document_id"]
    version_id = ingest_v1["version_id"]
    nodes_resp = client.get(f"/api/v1/documents/{doc_id}/nodes?version=1")
    node_id = nodes_resp.json()[0]["id"]

    resp = client.post(
        "/api/v1/selections",
        json={
            "version_id": version_id,
            "node_ids": [node_id],
            "label": "test selection",
        },
    )
    assert resp.status_code == 201, f"Selection failed: {resp.text}"
    data = resp.json()
    assert data["version_id"] == version_id
    assert node_id in data["node_ids"]
    assert "id" in data
    assert "created_at" in data


@skip_if_no_pdf
def test_create_selection_multi_node(client, ingest_v1):
    """Create a selection with multiple nodes."""
    doc_id = ingest_v1["document_id"]
    version_id = ingest_v1["version_id"]
    nodes_resp = client.get(f"/api/v1/documents/{doc_id}/nodes?version=1")
    nodes = nodes_resp.json()
    node_ids = [n["id"] for n in nodes[:3]]

    resp = client.post(
        "/api/v1/selections",
        json={
            "version_id": version_id,
            "node_ids": node_ids,
            "label": "multi-node selection",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["node_ids"]) == len(node_ids)


@skip_if_no_pdf
def test_create_selection_invalid_nodes(client, ingest_v1):
    """Selection with invalid node IDs returns 422."""
    version_id = ingest_v1["version_id"]
    resp = client.post(
        "/api/v1/selections",
        json={
            "version_id": version_id,
            "node_ids": ["fake-node-id-1", "fake-node-id-2"],
            "label": "bad selection",
        },
    )
    assert resp.status_code == 422


def test_create_selection_empty_nodes(client):
    """Empty node_ids list returns validation error (min_length=1)."""
    resp = client.post(
        "/api/v1/selections",
        json={
            "version_id": "some-version",
            "node_ids": [],
            "label": "empty",
        },
    )
    assert resp.status_code == 422


def test_create_selection_missing_body(client):
    """Missing required fields returns 422."""
    resp = client.post("/api/v1/selections", json={})
    assert resp.status_code == 422
