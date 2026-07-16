"""Ingestion API endpoint — POST /api/v1/documents.

Handles multipart PDF upload, delegates to IngestDocumentUseCase,
and returns the ingestion result. Rate limited at 10 requests/minute
per client. Idempotent: re-uploading same content returns existing version.

Requirements: 2.1, 4.3, 4.6, 12.2
"""

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from ct200.application.ingestion import IngestDocumentUseCase
from ct200.infrastructure.database.engine import get_session_factory
from ct200.transport.middleware.rate_limit import limiter

router = APIRouter(prefix="/api/v1", tags=["ingestion"])


@router.post("/documents")
@limiter.limit("10/minute")
async def ingest_document(
    request: Request,
    file: UploadFile = File(...),
    document_id: str | None = Query(default=None, description="Optional document ID for versioning"),
) -> JSONResponse:
    """Ingest a PDF document — parse, build tree, persist.

    Accepts multipart/form-data with a PDF file. Orchestrates the full
    pipeline: validate → parse → tree → idempotency check → persist.

    - Returns 201 with version details when new content is ingested.
    - Returns 200 with existing version reference when duplicate content is detected.
    - Rate limited to 10 requests per minute per client.
    """
    pdf_bytes = await file.read()
    filename = file.filename or "unknown.pdf"

    factory = get_session_factory()
    async with factory() as session:
        use_case = IngestDocumentUseCase(session)
        result = await use_case.execute(pdf_bytes, filename, document_id)

    status_code = 201 if result["is_new"] else 200
    return JSONResponse(content=result, status_code=status_code)
