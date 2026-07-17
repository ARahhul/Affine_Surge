"""CT200 QA Traceability System — FastAPI application.

Clean REST API for document ingestion, node browsing, version diffing,
selection creation, generation, staleness detection, and full-text search.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid as _uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ct200.database import (
    Document,
    Generation,
    Node,
    Selection,
    Version,
    get_session,
    ingest_document,
)
from ct200.generation.nim_client import (
    NIMClient,
    NIMSchemaError,
    NIMTimeoutError,
    NIMTransientError,
)
from ct200.generation.prompt_templates import build_prompt
from ct200.schemas import (
    CreateGenerationRequest,
    CreateSelectionRequest,
    GenerationResponse,
    SelectionResponse,
)

if TYPE_CHECKING:
    from ct200.models import DocumentNode

app = FastAPI(
    title="CT200 QA Traceability System",
    version="0.1.0",
    docs_url="/docs",
)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/ct200.db")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/api/v1/documents", status_code=201)
async def ingest(file: UploadFile = File(...)) -> JSONResponse:  # noqa: B008
    """Ingest a PDF document. Idempotent — duplicate content returns existing version."""
    from ct200.parser.pymupdf_parser import PyMuPDFParser
    from ct200.parser.tree_engine import TreeEngine
    from ct200.versioning.lineage_matcher import LineageMatcher

    pdf_bytes = await file.read()
    filename = file.filename or "unknown.pdf"

    # Parse and build tree
    parser = PyMuPDFParser()
    content = await parser.parse(pdf_bytes, filename)
    engine = TreeEngine()
    tree = engine.build_tree(content)

    # --- Lineage matching (Step 2e) ---
    # If a previous version exists for this document, match lineage
    session = get_session(DATABASE_URL)
    try:
        doc = session.query(Document).filter_by(name=filename).first()
        prev_tree = None
        if doc:
            latest_version = (
                session.query(Version)
                .filter_by(document_id=doc.id)
                .order_by(Version.version_number.desc())
                .first()
            )
            if latest_version:
                # Rebuild prev_tree from stored nodes
                prev_tree = _rebuild_tree_from_db(session, latest_version.id)

        if prev_tree is not None:
            matcher = LineageMatcher()
            matches = matcher.match_lineage(tree, prev_tree)
            # Apply lineage match results to the new tree's nodes
            match_map = {m.node_id: m for m in matches}
            _apply_lineage_matches(tree.root, match_map)

        # Flatten tree to node dicts for persistence
        nodes_data = _flatten_tree(tree.root)

        result = ingest_document(session, filename, pdf_bytes, nodes_data)
        status = 201 if result["is_new"] else 200
        return JSONResponse(content=result, status_code=status)
    finally:
        session.close()


def _flatten_tree(
    node: DocumentNode, result: list[dict[str, object]] | None = None
) -> list[dict[str, object]]:
    """Recursively flatten tree nodes into dicts for DB persistence."""
    if result is None:
        result = []
    result.append(
        {
            "id": node.id,
            "parent_id": node.parent_id,
            "heading": node.heading,
            "level": node.depth,
            "body": node.body,
            "content_hash": node.content_hash,
            "lineage_id": node.lineage_id,
            "match_strategy": (
                node.match_strategy.value
                if hasattr(node.match_strategy, "value")
                else node.match_strategy
            ),
            "confidence_score": node.confidence_score,
        }
    )
    for child in node.children:
        _flatten_tree(child, result)
    return result


def _rebuild_tree_from_db(session: object, version_id: str):
    """Rebuild a DocumentTree from persisted nodes for lineage comparison."""
    from ct200.models import DocumentNode as DN, DocumentTree, MatchStrategy

    nodes = (
        session.query(Node)
        .filter_by(version_id=version_id)
        .order_by(Node.position_index)
        .all()
    )
    if not nodes:
        return None

    # Build lookup
    dn_map: dict[str, DN] = {}
    for idx, n in enumerate(nodes):
        strategy = MatchStrategy.NEW
        if n.match_strategy and n.match_strategy in MatchStrategy.__members__.values():
            strategy = MatchStrategy(n.match_strategy)
        dn = DN(
            id=n.id,
            version_id=version_id,
            parent_id=n.parent_id,
            heading=n.heading or "",
            body=n.body or "",
            depth=n.level,
            order_index=idx,
            lineage_id=n.lineage_id,
            content_hash=n.content_hash or "",
            match_strategy=strategy,
            confidence_score=n.confidence_score or 1.0,
        )
        dn_map[n.id] = dn

    # Build parent-child relationships
    root = None
    for n in nodes:
        dn = dn_map[n.id]
        if n.parent_id and n.parent_id in dn_map:
            dn_map[n.parent_id].children.append(dn)
        else:
            if root is None:
                root = dn

    if root is None:
        root = dn_map[nodes[0].id]

    return DocumentTree(
        root=root,
        node_count=len(nodes),
        max_depth=max(n.level for n in nodes),
    )


def _apply_lineage_matches(node: DocumentNode, match_map: dict) -> None:
    """Apply lineage match results to tree nodes recursively."""
    if node.id in match_map:
        match = match_map[node.id]
        node.lineage_id = match.lineage_id
        node.match_strategy = match.strategy
        node.confidence_score = match.confidence
    for child in node.children:
        _apply_lineage_matches(child, match_map)


@app.get("/api/v1/documents/{doc_id}/nodes")
def get_nodes(doc_id: str, version: int | None = Query(default=None)) -> list[dict[str, object]]:
    """Browse document nodes. Defaults to latest version if omitted."""
    session = get_session(DATABASE_URL)
    try:
        if version:
            ver = (
                session.query(Version).filter_by(document_id=doc_id, version_number=version).first()
            )
        else:
            ver = (
                session.query(Version)
                .filter_by(document_id=doc_id)
                .order_by(Version.version_number.desc())
                .first()
            )
        if not ver:
            raise HTTPException(404, "Version not found")
        nodes = (
            session.query(Node)
            .filter_by(version_id=ver.id)
            .filter(Node.parent_id.isnot(None))
            .order_by(Node.position_index)
            .all()
        )
        return [
            {
                "id": n.id,
                "heading": n.heading,
                "level": n.level,
                "body": n.body[:200],
                "content_hash": n.content_hash,
                "position_index": n.position_index,
                "lineage_id": n.lineage_id,
                "parent_id": n.parent_id,
            }
            for n in nodes
        ]
    finally:
        session.close()


@app.get("/api/v1/nodes/{node_id}/diff")
def node_diff(node_id: str) -> dict[str, object]:
    """Lightweight diff — compare this node across all versions by lineage_id."""
    session = get_session(DATABASE_URL)
    try:
        node = session.get(Node, node_id)
        if not node:
            raise HTTPException(404, "Node not found")
        # Single indexed query on ix_node_lineage
        versions = (
            session.query(Node.version_id, Node.content_hash, Node.heading, Node.level)
            .filter_by(lineage_id=node.lineage_id)
            .order_by(Node.version_id)
            .all()
        )
        history = [
            {
                "version_id": v[0],
                "content_hash": v[1],
                "heading": v[2],
                "level": v[3],
            }
            for v in versions
        ]
        return {"node_id": node_id, "lineage_id": node.lineage_id, "history": history}
    finally:
        session.close()


@app.post("/api/v1/selections", status_code=201)
def create_selection(body: CreateSelectionRequest) -> SelectionResponse:
    """Create an immutable, version-pinned selection."""
    import uuid as _uuid
    from datetime import datetime

    session = get_session(DATABASE_URL)
    try:
        # Batch validate: single query instead of N+1
        valid_nodes = (
            session.query(Node.id)
            .filter(
                Node.id.in_(body.node_ids),
                Node.version_id == body.version_id,
            )
            .all()
        )
        valid_ids = {row[0] for row in valid_nodes}
        missing = [nid for nid in body.node_ids if nid not in valid_ids]
        if missing:
            raise HTTPException(422, f"Nodes not in version {body.version_id}: {missing}")
        sel = Selection(
            id=str(_uuid.uuid4()),
            version_id=body.version_id,
            node_ids_json=json.dumps(body.node_ids),
            created_at=datetime.now(UTC).isoformat(),
            label=body.label,
        )
        session.add(sel)
        session.commit()
        return SelectionResponse(
            id=str(sel.id),
            version_id=str(sel.version_id),
            node_ids=body.node_ids,
            created_at=str(sel.created_at),
        )
    finally:
        session.close()



# ===========================================================================
# Generation routes (2a, 2b)
# ===========================================================================


@app.post("/api/v1/generations", status_code=201)
async def create_generation(body: CreateGenerationRequest) -> JSONResponse:
    """Create a new QA test case generation from a selection.

    Policy: Always creates a new generation (not idempotent).
    See ADR 0003 for storage rationale.

    Error mapping:
        NIMSchemaError → 502 (upstream returned invalid schema)
        NIMTimeoutError → 504 (upstream timeout)
        NIMTransientError → 502 (upstream unavailable after retries)
    """
    session = get_session(DATABASE_URL)
    try:
        # Look up selection
        selection = session.get(Selection, body.selection_id)
        if not selection:
            raise HTTPException(404, "Selection not found")

        node_ids = json.loads(selection.node_ids_json)
        version_id = selection.version_id

        # Fetch node content for each node_id
        nodes = (
            session.query(Node)
            .filter(Node.id.in_(node_ids), Node.version_id == version_id)
            .all()
        )
        if not nodes:
            raise HTTPException(404, "No nodes found for selection")

        node_contents = [
            {"heading": n.heading, "body": n.body} for n in nodes
        ]

        # Build source_hashes: node_id → content_hash
        source_hashes = {n.id: n.content_hash for n in nodes}

        # Build prompt
        messages = build_prompt(node_contents)

        # Create generation record (pending)
        gen_id = str(_uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        generation = Generation(
            id=gen_id,
            selection_id=body.selection_id,
            status="pending",
            source_hashes_json=json.dumps(source_hashes),
            created_at=now,
            model_id=os.getenv("NIM_MODEL_ID", "meta/llama-3.1-70b-instruct"),
        )
        session.add(generation)
        session.commit()

        # Call NIM API
        try:
            nim_client = NIMClient(
                base_url=os.getenv(
                    "NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"
                ),
                api_key=os.getenv("NVIDIA_NIM_API_KEY", ""),
                model_id=os.getenv("NIM_MODEL_ID", "meta/llama-3.1-70b-instruct"),
            )
            nim_response = await nim_client.generate(messages)

            # Update generation with success
            generation.status = "completed"
            generation.output_json = nim_response.raw_json
            generation.input_tokens = nim_response.input_tokens
            generation.output_tokens = nim_response.output_tokens
            session.commit()

            return JSONResponse(
                content={"id": gen_id, "status": "completed"},
                status_code=201,
            )

        except NIMSchemaError as exc:
            generation.status = "failed"
            generation.error_message = str(exc)
            session.commit()
            raise HTTPException(502, f"NIM schema validation failed: {exc}")

        except NIMTimeoutError as exc:
            generation.status = "failed"
            generation.error_message = str(exc)
            session.commit()
            raise HTTPException(504, f"NIM request timed out: {exc}")

        except NIMTransientError as exc:
            generation.status = "failed"
            generation.error_message = str(exc)
            session.commit()
            raise HTTPException(502, f"NIM service unavailable: {exc}")

        except Exception as exc:
            generation.status = "failed"
            generation.error_message = str(exc)
            session.commit()
            raise HTTPException(502, f"Generation failed: {exc}")

    finally:
        session.close()


@app.get("/api/v1/generations/{gen_id}")
def get_generation(gen_id: str) -> dict:
    """Return the stored generation record."""
    session = get_session(DATABASE_URL)
    try:
        gen = session.get(Generation, gen_id)
        if not gen:
            raise HTTPException(404, "Generation not found")
        return {
            "id": gen.id,
            "selection_id": gen.selection_id,
            "status": gen.status,
            "source_hashes": json.loads(gen.source_hashes_json) if gen.source_hashes_json else {},
            "output": json.loads(gen.output_json) if gen.output_json else None,
            "input_tokens": gen.input_tokens,
            "output_tokens": gen.output_tokens,
            "model_id": gen.model_id,
            "error_message": gen.error_message,
            "created_at": gen.created_at,
        }
    finally:
        session.close()


@app.get("/api/v1/selections/{sel_id}/generations")
def get_generations_for_selection(sel_id: str) -> list[dict]:
    """Return all generations for a selection."""
    session = get_session(DATABASE_URL)
    try:
        selection = session.get(Selection, sel_id)
        if not selection:
            raise HTTPException(404, "Selection not found")
        gens = session.query(Generation).filter_by(selection_id=sel_id).all()
        return [
            {
                "id": g.id,
                "status": g.status,
                "input_tokens": g.input_tokens,
                "output_tokens": g.output_tokens,
                "created_at": g.created_at,
            }
            for g in gens
        ]
    finally:
        session.close()


@app.get("/api/v1/nodes/{node_id}/generations")
def get_generations_for_node(node_id: str) -> list[dict]:
    """Return all generations whose source_hashes contain the given node_id."""
    session = get_session(DATABASE_URL)
    try:
        node = session.get(Node, node_id)
        if not node:
            raise HTTPException(404, "Node not found")
        # Query generations where source_hashes_json contains the node_id
        all_gens = session.query(Generation).all()
        matching = []
        for g in all_gens:
            if g.source_hashes_json and node_id in g.source_hashes_json:
                # Verify it's actually a key, not a substring match
                hashes = json.loads(g.source_hashes_json)
                if node_id in hashes:
                    matching.append({
                        "id": g.id,
                        "selection_id": g.selection_id,
                        "status": g.status,
                        "created_at": g.created_at,
                    })
        return matching
    finally:
        session.close()


# ===========================================================================
# Staleness route (2c)
# ===========================================================================


@app.get("/api/v1/generations/{gen_id}/staleness")
def get_staleness(gen_id: str) -> dict:
    """Check staleness of a generation against current document version.

    For each node in the generation's source_hashes:
    - Find the node's lineage_id
    - Find the latest version's node with that lineage_id
    - Compare stored hash vs current hash
    - Return per-node status: unchanged | changed | removed
    """
    session = get_session(DATABASE_URL)
    try:
        gen = session.get(Generation, gen_id)
        if not gen:
            raise HTTPException(404, "Generation not found")

        source_hashes = json.loads(gen.source_hashes_json) if gen.source_hashes_json else {}
        if not source_hashes:
            return {
                "generation_id": gen_id,
                "is_stale": False,
                "nodes": [],
            }

        # Get the selection to find the document
        selection = session.get(Selection, gen.selection_id)
        if not selection:
            raise HTTPException(404, "Selection not found")

        # Get the version to find the document_id
        version = session.get(Version, selection.version_id)
        if not version:
            raise HTTPException(404, "Version not found")

        # Get the latest version for this document
        latest_version = (
            session.query(Version)
            .filter_by(document_id=version.document_id)
            .order_by(Version.version_number.desc())
            .first()
        )

        node_results = []
        is_stale = False

        for node_id, stored_hash in source_hashes.items():
            # Find original node to get its lineage_id
            original_node = session.get(Node, node_id)
            if not original_node:
                node_results.append({
                    "lineage_id": node_id,
                    "status": "removed",
                    "old_hash": stored_hash,
                    "new_hash": None,
                })
                is_stale = True
                continue

            lineage_id = original_node.lineage_id

            # Find the corresponding node in the latest version by lineage_id
            current_node = (
                session.query(Node)
                .filter_by(version_id=latest_version.id, lineage_id=lineage_id)
                .first()
            )

            if not current_node:
                node_results.append({
                    "lineage_id": lineage_id,
                    "status": "removed",
                    "old_hash": stored_hash,
                    "new_hash": None,
                })
                is_stale = True
            elif current_node.content_hash != stored_hash:
                node_results.append({
                    "lineage_id": lineage_id,
                    "status": "changed",
                    "old_hash": stored_hash,
                    "new_hash": current_node.content_hash,
                })
                is_stale = True
            else:
                node_results.append({
                    "lineage_id": lineage_id,
                    "status": "unchanged",
                    "old_hash": stored_hash,
                    "new_hash": current_node.content_hash,
                })

        return {
            "generation_id": gen_id,
            "is_stale": is_stale,
            "nodes": node_results,
        }
    finally:
        session.close()


# ===========================================================================
# Search route (2d)
# ===========================================================================


@app.get("/api/v1/documents/{doc_id}/search")
def search_nodes(
    doc_id: str,
    q: str = Query(..., min_length=1),
    version: int | None = Query(default=None),
) -> list[dict]:
    """Full-text search over document nodes using FTS5.

    Searches the nodes_fts table and filters by document version.
    Returns matching nodes with highlighted snippets.
    """
    session = get_session(DATABASE_URL)
    try:
        # Determine version
        if version:
            ver = (
                session.query(Version)
                .filter_by(document_id=doc_id, version_number=version)
                .first()
            )
        else:
            ver = (
                session.query(Version)
                .filter_by(document_id=doc_id)
                .order_by(Version.version_number.desc())
                .first()
            )
        if not ver:
            raise HTTPException(404, "Version not found")

        # Query FTS5 table
        fts_query = text(
            "SELECT node_id, highlight(nodes_fts, 1, '<b>', '</b>') as heading_hl, "
            "highlight(nodes_fts, 2, '<b>', '</b>') as body_hl "
            "FROM nodes_fts WHERE nodes_fts MATCH :query"
        )
        results = session.execute(fts_query, {"query": q}).fetchall()

        # Filter to nodes in this version
        version_node_ids = {
            row[0]
            for row in session.query(Node.id).filter_by(version_id=ver.id).all()
        }

        matched = []
        for row in results:
            node_id, heading_hl, body_hl = row
            if node_id in version_node_ids:
                matched.append({
                    "node_id": node_id,
                    "heading_highlight": heading_hl,
                    "body_highlight": body_hl[:300],
                })

        return matched
    finally:
        session.close()
