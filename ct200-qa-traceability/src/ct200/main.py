"""CT200 QA Traceability System — FastAPI application.

Clean REST API for document ingestion, node browsing, version diffing,
selection creation, and staleness detection.
"""

import os

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from ct200.database import (
    Document,
    Node,
    Selection,
    Version,
    get_session,
    ingest_document,
)
from ct200.schemas import (
    CreateSelectionRequest,
    NodeDiff,
    SelectionResponse,
    StalenessResponse,
)

app = FastAPI(
    title="CT200 QA Traceability System",
    version="0.1.0",
    docs_url="/docs",
)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/ct200.db")


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/api/v1/documents", status_code=201)
async def ingest(file: UploadFile = File(...)):
    """Ingest a PDF document. Idempotent — duplicate content returns existing version."""
    from ct200.parser.pymupdf_parser import PyMuPDFParser
    from ct200.parser.tree_engine import TreeEngine

    pdf_bytes = await file.read()
    filename = file.filename or "unknown.pdf"

    # Parse and build tree
    parser = PyMuPDFParser()
    import asyncio
    content = await parser.parse(pdf_bytes, filename)
    engine = TreeEngine()
    tree = engine.build_tree(content)

    # Flatten tree to node dicts for persistence
    nodes_data = _flatten_tree(tree.root)

    session = get_session(DATABASE_URL)
    try:
        result = ingest_document(session, filename, pdf_bytes, nodes_data)
        status = 201 if result["is_new"] else 200
        return JSONResponse(content=result, status_code=status)
    finally:
        session.close()


def _flatten_tree(node, result=None):
    """Recursively flatten tree nodes into dicts for DB persistence."""
    if result is None:
        result = []
    result.append({
        "id": node.id,
        "parent_id": node.parent_id,
        "heading": node.heading,
        "level": node.depth,
        "body": node.body,
        "content_hash": node.content_hash,
        "lineage_id": node.lineage_id,
        "match_strategy": node.match_strategy.value if hasattr(node.match_strategy, 'value') else node.match_strategy,
        "confidence_score": node.confidence_score,
    })
    for child in node.children:
        _flatten_tree(child, result)
    return result


@app.get("/api/v1/documents/{doc_id}/nodes")
def get_nodes(doc_id: str, version: int | None = Query(default=None)):
    """Browse document nodes. Defaults to latest version if omitted."""
    session = get_session(DATABASE_URL)
    try:
        if version:
            ver = session.query(Version).filter_by(
                document_id=doc_id, version_number=version
            ).first()
        else:
            ver = session.query(Version).filter_by(document_id=doc_id)\
                .order_by(Version.version_number.desc()).first()
        if not ver:
            raise HTTPException(404, "Version not found")
        nodes = session.query(Node).filter_by(version_id=ver.id)\
            .order_by(Node.position_index).all()
        return [{
            "id": n.id, "heading": n.heading, "level": n.level,
            "body": n.body[:200], "content_hash": n.content_hash,
            "position_index": n.position_index, "lineage_id": n.lineage_id,
            "parent_id": n.parent_id,
        } for n in nodes]
    finally:
        session.close()


@app.get("/api/v1/nodes/{node_id}/diff")
def node_diff(node_id: str):
    """Lightweight diff — compare this node across all versions by lineage_id."""
    session = get_session(DATABASE_URL)
    try:
        node = session.get(Node, node_id)
        if not node:
            raise HTTPException(404, "Node not found")
        # Single indexed query on ix_node_lineage
        versions = session.query(
            Node.version_id, Node.content_hash, Node.heading, Node.level
        ).filter_by(lineage_id=node.lineage_id)\
            .order_by(Node.version_id).all()
        history = [{
            "version_id": v[0], "content_hash": v[1],
            "heading": v[2], "level": v[3],
        } for v in versions]
        return {"node_id": node_id, "lineage_id": node.lineage_id, "history": history}
    finally:
        session.close()


@app.post("/api/v1/selections", status_code=201)
def create_selection(body: CreateSelectionRequest):
    """Create an immutable, version-pinned selection."""
    import uuid as _uuid
    from datetime import datetime, timezone
    session = get_session(DATABASE_URL)
    try:
        # Batch validate: single query instead of N+1
        valid_nodes = session.query(Node.id).filter(
            Node.id.in_(body.node_ids),
            Node.version_id == body.version_id,
        ).all()
        valid_ids = {row[0] for row in valid_nodes}
        missing = [nid for nid in body.node_ids if nid not in valid_ids]
        if missing:
            raise HTTPException(422, f"Nodes not in version {body.version_id}: {missing}")
        sel = Selection(
            id=str(_uuid.uuid4()), version_id=body.version_id,
            node_ids_json=__import__("json").dumps(body.node_ids),
            created_at=datetime.now(timezone.utc).isoformat(), label=body.label,
        )
        session.add(sel)
        session.commit()
        return SelectionResponse(
            id=sel.id, version_id=sel.version_id,
            node_ids=body.node_ids, created_at=sel.created_at,
        )
    finally:
        session.close()
