"""Selection API routes.

POST /api/v1/selections — Create an immutable, version-pinned selection
GET /api/v1/selections/{id} — Retrieve a selection by ID

Requirements: 7.1, 7.2
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ct200.application.selection import (
    CreateSelectionUseCase,
    EmptySelectionError,
    InvalidNodeIDsError,
    VersionNotFoundError,
)
from ct200.infrastructure.database.engine import get_session_factory

router = APIRouter(prefix="/api/v1", tags=["selections"])


class CreateSelectionRequest(BaseModel):
    """Request body for creating a selection."""

    version_id: str = Field(..., description="Version to pin the selection to")
    node_ids: list[str] = Field(
        ..., description="List of node IDs to include", min_length=1
    )
    label: str = Field(default="", description="Optional human-readable label")


class SelectionResponse(BaseModel):
    """Response body for a selection."""

    id: str
    version_id: str
    node_ids: list[str]
    created_at: str
    label: str


@router.post("/selections", status_code=201)
async def create_selection(
    request: Request,
    body: CreateSelectionRequest,
) -> JSONResponse:
    """Create an immutable, version-pinned selection of document nodes.

    Validates all node IDs exist in the specified version.
    Selections are write-once — no mutation after creation (CP-7.1).
    """
    factory = get_session_factory()
    async with factory() as session:
        use_case = CreateSelectionUseCase(session)
        try:
            selection = await use_case.execute(
                version_id=body.version_id,
                node_ids=body.node_ids,
                label=body.label,
            )
        except EmptySelectionError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except InvalidNodeIDsError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": str(exc),
                    "invalid_ids": exc.invalid_ids,
                },
            )
        except VersionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    return JSONResponse(
        status_code=201,
        content={
            "id": selection.id,
            "version_id": selection.version_id,
            "node_ids": selection.node_ids,
            "created_at": selection.created_at,
            "label": selection.label,
        },
    )


@router.get("/selections/{selection_id}")
async def get_selection(
    request: Request,
    selection_id: str,
) -> JSONResponse:
    """Retrieve a selection by its ID."""
    factory = get_session_factory()
    async with factory() as session:
        use_case = CreateSelectionUseCase(session)
        selection = await use_case.get_by_id(selection_id)

    if selection is None:
        raise HTTPException(status_code=404, detail="Selection not found")

    return JSONResponse(
        content={
            "id": selection.id,
            "version_id": selection.version_id,
            "node_ids": selection.node_ids,
            "created_at": selection.created_at,
            "label": selection.label,
        }
    )
