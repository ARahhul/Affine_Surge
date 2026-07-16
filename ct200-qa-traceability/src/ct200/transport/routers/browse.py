"""Browse and search API endpoints.

Provides tree browsing, single-node retrieval, and change detection
between document versions.

Requirements: 6.1, 6.2, 6.3, 6.6, 6.7, 6.8, CP-6.1, CP-6.3
"""

import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ct200.domain.exceptions import NotFoundError
from ct200.infrastructure.database.engine import get_session_factory
from ct200.infrastructure.database.repositories.node import NodeRepository
from ct200.infrastructure.database.repositories.version import VersionRepository
from ct200.transport.middleware.rate_limit import limiter

router = APIRouter(prefix="/api/v1", tags=["browse"])


@router.get("/documents/{doc_id}/versions/{version_id}/tree")
@limiter.limit("60/minute")
async def browse_tree(
    request: Request,
    doc_id: str,
    version_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    """Browse document tree hierarchy for a specific version.

    Returns paginated list of nodes with heading, depth, order_index,
    content_hash, and child_count. Supports pagination with default
    page_size=20, max 100.

    Requirements: 6.1, 6.2, 6.6, 6.7, CP-6.1
    """
    start = time.perf_counter()

    factory = get_session_factory()
    async with factory() as session:
        version_repo = VersionRepository(session)
        node_repo = NodeRepository(session)

        # Verify version exists
        version = await version_repo.get_by_id(version_id)
        if not version:
            raise NotFoundError(
                f"Version not found: {version_id}",
                details={"version_id": version_id},
            )

        # Get all nodes for this version
        all_nodes = await node_repo.get_tree(version_id)

        # Build parent_id -> child count map
        child_counts: dict[str | None, int] = {}
        for node in all_nodes:
            pid = node.parent_id
            child_counts[pid] = child_counts.get(pid, 0) + 1

        # Build response data
        nodes_data = []
        for node in all_nodes:
            nodes_data.append({
                "id": node.id,
                "heading": node.heading,
                "depth": node.depth,
                "order_index": node.order_index,
                "content_hash": node.content_hash,
                "lineage_id": node.lineage_id,
                "parent_id": node.parent_id,
                "child_count": child_counts.get(node.id, 0),
            })

        # Paginate
        total = len(nodes_data)
        offset = (page - 1) * page_size
        paginated = nodes_data[offset : offset + page_size]

        latency_ms = (time.perf_counter() - start) * 1000

        return JSONResponse(content={
            "version_id": version_id,
            "document_id": doc_id,
            "total_nodes": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
            "nodes": paginated,
            "latency_ms": round(latency_ms, 2),
        })


@router.get("/nodes/{node_id}")
@limiter.limit("60/minute")
async def get_node(request: Request, node_id: str) -> JSONResponse:
    """Retrieve a single document node by ID.

    Returns full node details including heading, body, depth, order_index,
    content_hash, lineage_id, parent_id, and children list.

    Requirements: 6.3
    """
    start = time.perf_counter()

    factory = get_session_factory()
    async with factory() as session:
        node_repo = NodeRepository(session)
        node = await node_repo.get_by_id(node_id)

        if not node:
            raise NotFoundError(
                f"Node not found: {node_id}",
                details={"node_id": node_id},
            )

        # Get children for this node
        all_version_nodes = await node_repo.get_tree(node.version_id)
        children = [
            {
                "id": n.id,
                "heading": n.heading,
                "depth": n.depth,
                "order_index": n.order_index,
            }
            for n in all_version_nodes
            if n.parent_id == node_id
        ]

        latency_ms = (time.perf_counter() - start) * 1000

        return JSONResponse(content={
            "id": node.id,
            "version_id": node.version_id,
            "parent_id": node.parent_id,
            "heading": node.heading,
            "body": node.body,
            "depth": node.depth,
            "parsed_number": node.parsed_number,
            "order_index": node.order_index,
            "lineage_id": node.lineage_id,
            "content_hash": node.content_hash,
            "match_strategy": node.match_strategy,
            "confidence_score": node.confidence_score,
            "lineage_status": node.lineage_status,
            "child_count": len(children),
            "children": children,
            "latency_ms": round(latency_ms, 2),
        })


@router.get("/documents/{doc_id}/versions/{version_id}/changes")
@limiter.limit("30/minute")
async def get_changes(
    request: Request,
    doc_id: str,
    version_id: str,
    prev_version_id: str = Query(..., description="Previous version ID to compare against"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    """Detect changes between two versions of a document.

    Returns list of changed nodes with previous_hash, current_hash,
    and change_type (added, modified, removed).

    Requirements: 6.8, CP-6.3
    """
    start = time.perf_counter()

    factory = get_session_factory()
    async with factory() as session:
        version_repo = VersionRepository(session)

        # Verify both versions exist
        current_version = await version_repo.get_by_id(version_id)
        if not current_version:
            raise NotFoundError(
                f"Version not found: {version_id}",
                details={"version_id": version_id},
            )

        prev_version = await version_repo.get_by_id(prev_version_id)
        if not prev_version:
            raise NotFoundError(
                f"Previous version not found: {prev_version_id}",
                details={"prev_version_id": prev_version_id},
            )

        # Delegate to use case
        from ct200.application.browse import BrowseTreeUseCase

        use_case = BrowseTreeUseCase(session)
        changes = await use_case.get_changes_since(version_id, prev_version_id)

        # Paginate
        total = len(changes)
        offset = (page - 1) * page_size
        paginated = changes[offset : offset + page_size]

        latency_ms = (time.perf_counter() - start) * 1000

        return JSONResponse(content={
            "document_id": doc_id,
            "version_id": version_id,
            "prev_version_id": prev_version_id,
            "total_changes": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
            "changes": paginated,
            "latency_ms": round(latency_ms, 2),
        })
