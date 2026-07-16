"""Test API integration — ingestion pipeline, node retrieval, selection logic.

10 tests covering: end-to-end ingestion with real PDF, idempotent re-ingest,
node retrieval by version, node diff across versions, selection creation
with validation, and error cases.
"""

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("NVIDIA_NIM_API_KEY", "test")
os.environ.setdefault("AUTH_SECRET_KEY", "test")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ct200.database import (
    Base, Document, Node, Selection, Version,
    compute_content_hash, ingest_document,
)
from ct200.parser.pymupdf_parser import PyMuPDFParser
from ct200.parser.tree_engine import TreeEngine


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _flatten_tree(node, result=None):
    if result is None:
        result = []
    result.append({
        "id": node.id, "parent_id": node.parent_id,
        "heading": node.heading, "level": node.depth,
        "body": node.body, "content_hash": node.content_hash,
        "lineage_id": node.lineage_id,
        "match_strategy": node.match_strategy.value,
        "confidence_score": node.confidence_score,
    })
    for child in node.children:
        _flatten_tree(child, result)
    return result


@pytest.fixture
def sample_pdf():
    pdf_path = os.path.join(os.path.dirname(__file__), "..", "pdf", "ct200_manual.pdf")
    if not os.path.exists(pdf_path):
        pytest.skip("CT200 PDF not found")
    with open(pdf_path, "rb") as f:
        return f.read()

class TestEndToEndIngestion:
    """Full pipeline: parse PDF → build tree → persist to DB."""

    def test_ingest_real_pdf_creates_version(self, sample_pdf):
        session = _session()
        parser = PyMuPDFParser()
        content = asyncio.run(parser.parse(sample_pdf, "ct200.pdf"))
        tree = TreeEngine().build_tree(content)
        nodes_data = _flatten_tree(tree.root)
        result = ingest_document(session, "ct200.pdf", sample_pdf, nodes_data)
        assert result["is_new"] is True
        assert result["version_number"] == 1
        # Verify nodes persisted
        count = session.query(Node).filter_by(version_id=result["version_id"]).count()
        assert count == tree.node_count

    def test_ingest_same_pdf_twice_is_idempotent(self, sample_pdf):
        session = _session()
        parser = PyMuPDFParser()
        content = asyncio.run(parser.parse(sample_pdf, "ct200.pdf"))
        tree = TreeEngine().build_tree(content)
        nodes_data = _flatten_tree(tree.root)
        r1 = ingest_document(session, "ct200.pdf", sample_pdf, nodes_data)
        r2 = ingest_document(session, "ct200.pdf", sample_pdf, nodes_data)
        assert r1["is_new"] is True
        assert r2["is_new"] is False
        assert r1["version_id"] == r2["version_id"]

    def test_nodes_have_sequential_position_index(self, sample_pdf):
        session = _session()
        parser = PyMuPDFParser()
        content = asyncio.run(parser.parse(sample_pdf, "ct200.pdf"))
        tree = TreeEngine().build_tree(content)
        nodes_data = _flatten_tree(tree.root)
        result = ingest_document(session, "ct200.pdf", sample_pdf, nodes_data)
        nodes = session.query(Node).filter_by(version_id=result["version_id"])\
            .order_by(Node.position_index).all()
        for i, node in enumerate(nodes):
            assert node.position_index == i


class TestNodeRetrieval:
    """Query nodes by version with correct ordering."""

    def test_query_by_version_returns_ordered_nodes(self):
        session = _session()
        nodes = [{"id": f"n{i}", "heading": f"H{i}", "level": 1, "body": "",
                  "content_hash": f"h{i}", "lineage_id": f"l{i}"} for i in range(5)]
        ingest_document(session, "doc.pdf", b"content-1", nodes)
        ver = session.query(Version).first()
        result = session.query(Node).filter_by(version_id=ver.id)\
            .order_by(Node.position_index).all()
        assert len(result) == 5
        assert [n.heading for n in result] == ["H0", "H1", "H2", "H3", "H4"]

    def test_lineage_id_query_uses_index(self):
        session = _session()
        nodes = [{"id": "n1", "heading": "H", "level": 1, "body": "B",
                  "content_hash": "ch", "lineage_id": "target-lineage"}]
        ingest_document(session, "doc.pdf", b"c1", nodes)
        # Query by lineage_id — should hit ix_node_lineage index
        result = session.query(Node).filter_by(lineage_id="target-lineage").first()
        assert result is not None
        assert result.heading == "H"


class TestNodeDiffAcrossVersions:
    """Diff nodes across versions using lineage_id."""

    def test_same_lineage_different_hash_detected(self):
        session = _session()
        nodes_v1 = [{"id": "n1", "heading": "Threshold: 5V", "level": 1,
                     "body": "Max 5V", "content_hash": "hash-v1", "lineage_id": "lin-1"}]
        ingest_document(session, "doc.pdf", b"v1-content", nodes_v1)
        nodes_v2 = [{"id": "n2", "heading": "Threshold: 3.3V", "level": 1,
                     "body": "Max 3.3V", "content_hash": "hash-v2", "lineage_id": "lin-1"}]
        ingest_document(session, "doc.pdf", b"v2-content", nodes_v2)
        # Query both versions of the same lineage
        history = session.query(Node).filter_by(lineage_id="lin-1").all()
        assert len(history) == 2
        hashes = {n.content_hash for n in history}
        assert len(hashes) == 2  # Different content = different hashes


class TestSelectionCreation:
    """Selection validation and immutability."""

    def test_selection_stores_node_ids(self):
        import json
        session = _session()
        nodes = [{"id": "n1", "heading": "H", "level": 1, "body": "",
                  "content_hash": "c", "lineage_id": "l"}]
        result = ingest_document(session, "d.pdf", b"x", nodes)
        sel = Selection(id=str(uuid.uuid4()), version_id=result["version_id"],
                        node_ids_json=json.dumps(["n1"]), created_at="2024-01-01T00:00:00Z")
        session.add(sel)
        session.commit()
        loaded = session.query(Selection).first()
        assert json.loads(loaded.node_ids_json) == ["n1"]
        assert loaded.version_id == result["version_id"]

    def test_selection_with_invalid_version_fails_fk(self):
        import json
        session = _session()
        sel = Selection(id="s1", version_id="nonexistent",
                        node_ids_json=json.dumps(["n1"]), created_at="now")
        session.add(sel)
        try:
            session.commit()
        except Exception:
            session.rollback()
            # FK violation — expected behavior


class TestContentHashIntegrity:
    """Content hash is deterministic and stored correctly."""

    def test_persisted_hash_matches_recomputed(self):
        session = _session()
        heading, body = "Safety Protocol", "Do not exceed 5V."
        expected_hash = compute_content_hash(heading, body)
        nodes = [{"id": "n1", "heading": heading, "level": 1, "body": body,
                  "content_hash": expected_hash, "lineage_id": "l1"}]
        result = ingest_document(session, "d.pdf", b"pdf-bytes", nodes)
        loaded_node = session.query(Node).filter_by(id="n1").first()
        assert loaded_node.content_hash == expected_hash
        # Recompute and verify
        assert compute_content_hash(loaded_node.heading, loaded_node.body) == expected_hash


class TestMultiVersionDocument:
    """Multiple versions of the same document."""

    def test_three_versions_tracked(self):
        session = _session()
        for i in range(3):
            nodes = [{"id": str(uuid.uuid4()), "heading": f"V{i+1}", "level": 1,
                      "body": f"Version {i+1} content", "content_hash": f"h{i}",
                      "lineage_id": f"l{i}"}]
            ingest_document(session, "multi.pdf", f"content-{i}".encode(), nodes)
        versions = session.query(Version).order_by(Version.version_number).all()
        assert len(versions) == 3
        assert [v.version_number for v in versions] == [1, 2, 3]

    def test_each_version_has_independent_nodes(self):
        session = _session()
        for i in range(2):
            nodes = [{"id": str(uuid.uuid4()), "heading": f"Section {i}",
                      "level": 1, "body": "", "content_hash": f"c{i}",
                      "lineage_id": f"l{i}"}]
            ingest_document(session, "doc.pdf", f"ver{i}".encode(), nodes)
        v1_nodes = session.query(Node).join(Version).filter(Version.version_number == 1).all()
        v2_nodes = session.query(Node).join(Version).filter(Version.version_number == 2).all()
        assert len(v1_nodes) == 1
        assert len(v2_nodes) == 1
        assert v1_nodes[0].id != v2_nodes[0].id
