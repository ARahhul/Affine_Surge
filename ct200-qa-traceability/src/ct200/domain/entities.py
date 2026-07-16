"""Domain entities for the CT200 QA Traceability System."""

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
