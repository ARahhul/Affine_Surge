"""Unified Pydantic schemas for request/response models."""

from pydantic import BaseModel, Field


# --- Node & Tree ---

class NodeResponse(BaseModel):
    id: str
    heading: str
    level: int
    body: str
    content_hash: str
    position_index: int
    lineage_id: str
    parent_id: str | None = None


class NodeDiff(BaseModel):
    lineage_id: str
    change_type: str  # "direct" | "descendant" | "added" | "removed"
    old_hash: str = ""
    new_hash: str = ""


class DiffResponse(BaseModel):
    node_id: str
    lineage_id: str
    changes: list[NodeDiff] = Field(default_factory=list)


# --- Selection ---

class CreateSelectionRequest(BaseModel):
    version_id: str
    node_ids: list[str] = Field(..., min_length=1)
    label: str = ""


class SelectionResponse(BaseModel):
    id: str
    version_id: str
    node_ids: list[str]
    created_at: str


# --- Generation ---

class CreateGenerationRequest(BaseModel):
    selection_id: str


class GenerationResponse(BaseModel):
    id: str
    selection_id: str
    status: str
    input_tokens: int = 0
    output_tokens: int = 0
    error_message: str | None = None


# --- Impact / Staleness ---

class StalenessResponse(BaseModel):
    generation_id: str
    is_stale: bool
    changed_nodes: list[NodeDiff] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
