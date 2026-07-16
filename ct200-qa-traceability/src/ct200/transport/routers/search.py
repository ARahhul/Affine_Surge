"""FTS5 full-text search API endpoint.

Provides full-text search across node headings and body content,
scoped to a specific document version.

Requirements: 6.4, 6.5, 6.6, 6.7, CP-6.1, CP-6.2, CP-6.3
"""

import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ct200.domain.exceptions import NotFoundError, ValidationError
from ct200.infrastructure.database.engine import get_session_factory
from ct200.infrastructure.database.repositories.node import NodeRepository
from ct200.infrastructure.database.repositories.version import VersionRepository
from ct200.transport.middleware.rate_limit import limiter

router = APIRouter(prefix="/api/v1", tags=["search"])


@router.get("/search")
@limiter.limit("30/minute")
async def search_nodes(
    request: Request,
    q: str = Query(..., description="Search query (min 2 characters)"),
    version_id: str = Query(..., description="Version to search within"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    """Full-text search across node headings and body content.

    Scoped to a specific document version. Returns paginated results
    ranked by FTS5 relevance. Rejects queries shorter than 2 characters.

    Requirements: 6.4, 6.5, 6.6, 6.7, CP-6.2, CP-6.3
    """
    # Validate query length
    if len(q.strip()) < 2:
        raise ValidationError(
            "Search query must be at least 2 characters",
            details={"query": q},
            code="QUERY_TOO_SHORT",
        )

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

        # Perform FTS5 search
        offset = (page - 1) * page_size
        results = await node_repo.search_fts(
            q.strip(), version_id, page_size, offset
        )

        nodes_data = [
            {
                "id": node.id,
                "heading": node.heading,
                "body": node.body[:200] + "..." if len(node.body) > 200 else node.body,
                "depth": node.depth,
                "order_index": node.order_index,
                "content_hash": node.content_hash,
                "lineage_id": node.lineage_id,
                "parent_id": node.parent_id,
            }
            for node in results
        ]

        latency_ms = (time.perf_counter() - start) * 1000

        return JSONResponse(content={
            "query": q,
            "version_id": version_id,
            "page": page,
            "page_size": page_size,
            "result_count": len(nodes_data),
            "results": nodes_data,
            "latency_ms": round(latency_ms, 2),
        })
