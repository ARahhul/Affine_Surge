"""Domain entities for the CT200 QA Traceability System."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class BlockType(str, Enum):
    """Type classification for content blocks extracted from PDF documents."""

    HEADING = "heading"
    BODY = "body"
    TABLE = "table"
    LIST_ITEM = "list_item"


class ContentBlock(BaseModel):
    """A single content block extracted from a PDF page.

    Attributes:
        block_type: Classification of this block (heading, body, table, list_item).
        content: The text content of this block.
        page_number: 1-based page number where this block was found.
        level: Heading level (1-6), 0 for non-headings.
        bbox: Bounding box coordinates (x0, y0, x1, y1) or None.
    """

    block_type: BlockType
    content: str
    page_number: int
    level: int = 0
    bbox: tuple[float, float, float, float] | None = None


class ParsedPage(BaseModel):
    """A single parsed page with its content blocks and raw text.

    Attributes:
        page_number: 1-based page number.
        blocks: Ordered list of content blocks on this page.
        raw_text: Full raw text of the page (unstructured).
    """

    page_number: int
    blocks: list[ContentBlock] = Field(default_factory=list)
    raw_text: str = ""


class ParsedContent(BaseModel):
    """Complete parsed output from a PDF document.

    Attributes:
        filename: Original filename of the parsed document.
        total_pages: Total number of pages in the document.
        pages: List of parsed pages with per-page blocks.
        blocks: Flattened, ordered list of all content blocks across pages.
    """

    filename: str
    total_pages: int
    pages: list[ParsedPage] = Field(default_factory=list)
    blocks: list[ContentBlock] = Field(default_factory=list)


# --- Enums for Tree/Versioning ---


class MatchStrategy(str, Enum):
    """Strategy used for lineage matching between versions."""

    EXACT = "exact"
    HEADING = "heading"
    POSITIONAL = "positional"
    NEW = "new"


class LineageStatus(str, Enum):
    """Status of a lineage match."""

    MATCHED = "matched"
    NEEDS_REVIEW = "needs_review"
    NEW = "new"


class GenerationStatus(str, Enum):
    """Status of a QA generation attempt."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "generation_failed"


# --- Tree Entities ---


class DocumentNode(BaseModel):
    """A single node in the hierarchical document tree.

    Contains heading, body, depth, parent/children references,
    ordering, lineage tracking, and content hash.
    """

    id: str
    version_id: str
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
    """A complete validated document tree with a root node and metadata."""

    root: DocumentNode
    node_count: int = 0
    max_depth: int = 0


# --- Document/Version Entities ---


class Document(BaseModel):
    """A tracked document (the CT200 PDF)."""

    id: str
    name: str
    created_at: str
    updated_at: str


class Version(BaseModel):
    """A specific version of a document."""

    id: str
    document_id: str
    version_number: int
    content_hash: str
    ingested_at: str
    parser_report_json: str | None = None
    validation_report_json: str | None = None
    block_count: int = 0
    mapped_block_count: int = 0


# --- Selection and Generation ---


class Selection(BaseModel):
    """An immutable, version-pinned selection of document nodes."""

    id: str
    version_id: str
    node_ids: list[str]
    created_at: str
    label: str = ""


class GenerationRecord(BaseModel):
    """A record of a QA test case generation attempt."""

    id: str
    selection_id: str
    status: GenerationStatus = GenerationStatus.PENDING
    source_hashes: dict[str, str] = Field(default_factory=dict)  # node_id → content_hash
    output_json: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model_id: str = ""
    retry_count: int = 0
    error_message: str | None = None
    created_at: str = ""
    completed_at: str | None = None


# --- Versioning/Diff ---


class LineageMatch(BaseModel):
    """Result of matching a node across document versions."""

    node_id: str
    lineage_id: str
    strategy: MatchStrategy
    confidence: float = Field(ge=0.0, le=1.0)
    status: LineageStatus


class NodeChange(BaseModel):
    """A single node change in a version diff or impact report."""

    lineage_id: str
    change_type: str  # "direct" | "descendant" | "added" | "removed"
    old_hash: str = ""
    new_hash: str = ""
    diff_summary: str = ""


class VersionDiff(BaseModel):
    """Lightweight diff between two document versions."""

    version_a_id: str
    version_b_id: str
    added_nodes: list[str] = Field(default_factory=list)
    removed_nodes: list[str] = Field(default_factory=list)
    modified_nodes: list[NodeChange] = Field(default_factory=list)


class ImpactReport(BaseModel):
    """Staleness analysis for a generation record."""

    generation_id: str
    is_stale: bool = False
    changed_nodes: list[str] = Field(default_factory=list)  # lineage_ids
    changes: list[NodeChange] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
