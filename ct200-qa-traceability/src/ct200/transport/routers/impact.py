"""Impact analysis API endpoint.

GET /api/v1/impact/{generation_id} — Analyze staleness for a generation.

Compares stored source-hashes against current lineage hashes in the
latest document version. Returns whether the generation is stale,
which nodes changed, and the classification of each change.

Requirements: 8.1-8.6, CP-8.1
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ct200.application.impact import AnalyzeImpactUseCase
from ct200.infrastructure.database.engine import get_session_factory
from ct200.transport.middleware.rate_limit import limiter

router = APIRouter(prefix="/api/v1", tags=["impact"])


@router.get("/impact/{generation_id}")
@limiter.limit("30/minute")
async def analyze_impact(
    request: Request,
    generation_id: str,
) -> JSONResponse:
    """Analyze staleness for a specific generation record.

    Compares stored source-hashes against current lineage hashes.
    Returns whether the generation is stale, and which nodes changed.

    Staleness is a computed view — generation records are never mutated.
    """
    start = time.perf_counter()

    factory = get_session_factory()
    async with factory() as session:
        use_case = AnalyzeImpactUseCase(session)
        try:
            report = await use_case.execute(generation_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    latency_ms = (time.perf_counter() - start) * 1000

    return JSONResponse(content={
        "generation_id": report.generation_id,
        "is_stale": report.is_stale,
        "status": "stale" if report.is_stale else "current",
        "changed_nodes": report.changed_nodes,
        "changes": [
            {
                "lineage_id": c.lineage_id,
                "change_type": c.change_type,
                "old_hash": c.old_hash,
                "new_hash": c.new_hash,
                "diff_summary": c.diff_summary,
            }
            for c in report.changes
        ],
        "reasons": report.reasons,
        "latency_ms": round(latency_ms, 2),
    })
