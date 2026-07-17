"""Domain models — Pydantic entities and value objects used across the system.

Single source of truth for all domain types. No unnecessary abstractions.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum

from pydantic import BaseModel, Field

# --- Block Types (Parser) ---


class BlockType(StrEnum):
    HEADING = "heading"
    BODY = "body"
    TABLE = "table"
    LIST_ITEM = "list_item"


class ContentBlock(BaseModel):
    block_type: BlockType
    content: str
    page_number: int
    level: int = 0
    bbox: tuple[float, float, float, float] | None = None


class ParsedPage(BaseModel):
    page_number: int
    blocks: list[ContentBlock] = Field(default_factory=list)
    raw_text: str = ""


class ParsedContent(BaseModel):
    filename: str
    total_pages: int
    pages: list[ParsedPage] = Field(default_factory=list)
    blocks: list[ContentBlock] = Field(default_factory=list)


# --- Tree / Versioning ---


class MatchStrategy(StrEnum):
    EXACT = "exact"
    HEADING = "heading"
    POSITIONAL = "positional"
    NEW = "new"


class LineageStatus(StrEnum):
    MATCHED = "matched"
    NEEDS_REVIEW = "needs_review"
    NEW = "new"


class DocumentNode(BaseModel):
    id: str
    version_id: str = ""
    parent_id: str | None = None
    heading: str = ""
    body: str = ""
    depth: int = Field(ge=0, le=10)
    parsed_number: str = ""
    order_index: int = Field(ge=0)
    lineage_id: str = ""
    content_hash: str = ""
    match_strategy: MatchStrategy = MatchStrategy.NEW
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    lineage_status: LineageStatus = LineageStatus.NEW
    children: list[DocumentNode] = Field(default_factory=list)


class DocumentTree(BaseModel):
    root: DocumentNode
    node_count: int = 0
    max_depth: int = 0
    warnings: list[str] = Field(default_factory=list)


class LineageMatch(BaseModel):
    node_id: str
    lineage_id: str
    strategy: MatchStrategy
    confidence: float = Field(ge=0.0, le=1.0)
    status: LineageStatus


# --- Value Object Utilities ---


def compute_content_hash(heading: str, body: str) -> str:
    """SHA-256 of heading+body. Identical content → same hash (deterministic)."""
    return hashlib.sha256(f"{heading}\n{body}".encode()).hexdigest()


# --- Exceptions ---


class CT200Error(Exception):
    """Base domain error."""

    code: str = "INTERNAL_ERROR"
    status_code: int = 500

    def __init__(self, message: str = "", **kwargs: object) -> None:
        super().__init__(message)
        self.message = message
        self.details = kwargs


class FileTooLargeError(CT200Error):
    code = "FILE_TOO_LARGE"
    status_code = 413


class InvalidFileFormatError(CT200Error):
    code = "INVALID_FILE_FORMAT"
    status_code = 422


class PathologicalInputError(CT200Error):
    code = "PATHOLOGICAL_INPUT"
    status_code = 422


class ParsingError(CT200Error):
    code = "PARSING_ERROR"
    status_code = 422


class TreeValidationError(CT200Error):
    code = "TREE_VALIDATION_FAILED"
    status_code = 422


class CT200TimeoutError(CT200Error):
    code = "TIMEOUT"
    status_code = 504
