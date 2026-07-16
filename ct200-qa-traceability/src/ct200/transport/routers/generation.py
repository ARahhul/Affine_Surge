"""Generation API routes.

POST /api/v1/generations — Trigger QA test case generation for a selection
GET /api/v1/generations/{id} — Retrieve a generation record by ID

Per-client rate limited at 10 requests/minute on the generation endpoint (Req 7.11, 12.2).

Requirements: 7.3-7.11, 12.2
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ct200.application.generation import (
    GenerateTestCasesUseCase,
    SelectionNotFoundError,
)
from ct200.config import get_settings
from ct200.domain.entities import GenerationStatus
from ct200.infrastructure.database.engine import get_session_factory
from ct200.infrastructure.generation.nim_client import NIMClient
from ct200.transport.middleware.rate_limit import limiter

router = APIRouter(prefix="/api/v1", tags=["generation"])


class CreateGenerationRequest(BaseModel):
    """Request body for triggering generation."""

    selection_id: str = Field(
        ..., description="ID of the selection to generate test cases for"
    )


class GenerationResponse(BaseModel):
    """Response body for a generation record."""

    id: str
    selection_id: str
    status: str
    output_json: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model_id: str = ""
    retry_count: int = 0
    error_message: str | None = None
    created_at: str = ""
    completed_at: str | None = None


@router.post("/generations", status_code=201)
@limiter.limit("10/minute")
async def create_generation(
    request: Request,
    body: CreateGenerationRequest,
) -> JSONResponse:
    """Trigger QA test case generation for a selection.

    Orchestrates: selection → prompt → NIM → validate → persist.
    Rate limited to 10 requests per minute per client.
    """
    settings = get_settings()

    nim_client = NIMClient(
        base_url=settings.nvidia_nim_base_url,
        api_key=settings.nvidia_nim_api_key,
        model_id=settings.nvidia_nim_model_id,
        timeout_seconds=settings.generation_timeout_seconds,
        rate_limit_rpm=int(settings.rate_limit_generate.split("/")[0]),
    )

    factory = get_session_factory()
    async with factory() as session:
        use_case = GenerateTestCasesUseCase(session, nim_client)
        try:
            record = await use_case.execute(body.selection_id)
        except SelectionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    return JSONResponse(
        status_code=201,
        content={
            "id": record.id,
            "selection_id": record.selection_id,
            "status": record.status.value,
            "output_json": record.output_json,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "model_id": record.model_id,
            "retry_count": record.retry_count,
            "error_message": record.error_message,
            "created_at": record.created_at,
            "completed_at": record.completed_at,
        },
    )


@router.get("/generations/{generation_id}")
async def get_generation(
    request: Request,
    generation_id: str,
) -> JSONResponse:
    """Retrieve a generation record by its ID."""
    factory = get_session_factory()
    async with factory() as session:
        use_case = GenerateTestCasesUseCase(
            session,
            # NIM client not needed for reads — pass a dummy
            nim_client=NIMClient(
                base_url="",
                api_key="",
                model_id="",
            ),
        )
        record = await use_case.get_by_id(generation_id)

    if record is None:
        raise HTTPException(status_code=404, detail="Generation record not found")

    return JSONResponse(
        content={
            "id": record.id,
            "selection_id": record.selection_id,
            "status": record.status.value,
            "output_json": record.output_json,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "model_id": record.model_id,
            "retry_count": record.retry_count,
            "error_message": record.error_message,
            "created_at": record.created_at,
            "completed_at": record.completed_at,
        }
    )
