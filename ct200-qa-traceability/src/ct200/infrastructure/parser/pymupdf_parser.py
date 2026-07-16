"""PDF parser implementation using PyMuPDF (fitz).

Extracts headings, tables, numbered lists, and body text from PDF documents,
preserving original document ordering. Implements hardening against pathological
input including magic-byte validation, file size checks, and configurable timeout.
"""

import asyncio
import re
import time
from typing import Any

import fitz  # PyMuPDF

import structlog

from ct200.config import get_settings
from ct200.domain.entities import BlockType, ContentBlock, ParsedContent, ParsedPage
from ct200.domain.exceptions import (
    FileTooLargeError,
    InvalidFileFormatError,
    ParsingError,
    PathologicalInputError,
    TimeoutError as CT200TimeoutError,
)
from ct200.infrastructure.parser.header_footer_stripper import strip_headers_footers

logger = structlog.get_logger()

PDF_MAGIC_BYTES = b"%PDF-"
MAX_NESTING_DEPTH = 20
MAX_PAGE_CONTENT_BYTES = 50 * 1024 * 1024  # 50MB per page raw content

# Patterns for detecting numbered/bulleted list items
_LIST_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\d+\.\d+\.\d+[\.\s]"),  # "1.1.1" or "1.1.1 "
    re.compile(r"^\d+\.\d+[\s]"),  # "1.1 "
    re.compile(r"^\d+\.\s"),  # "1. "
    re.compile(r"^[a-z]\)\s"),  # "a) "
    re.compile(r"^[A-Z]\)\s"),  # "A) "
    re.compile(r"^[ivxIVX]+\)\s"),  # "iv) " roman numerals
    re.compile(r"^[•●○▪▸►◦–—-]\s"),  # bullet/dash points
]


class PyMuPDFParser:
    """PDF parser using PyMuPDF with hardening against pathological input.

    Implements the IParser protocol. Extracts structured content blocks
    (headings, tables, list items, body text) from PDF documents using
    font-size heuristics and spatial analysis for multi-column detection.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._max_file_size: int = settings.max_upload_size_mb * 1024 * 1024
        self._timeout_seconds: int = settings.parse_timeout_seconds

    async def parse(self, pdf_bytes: bytes, filename: str) -> ParsedContent:
        """Parse PDF bytes into structured content.

        Validates input, extracts content with timeout protection,
        and returns structured ParsedContent preserving document order.

        Args:
            pdf_bytes: Raw bytes of the PDF file.
            filename: Original filename for metadata and error reporting.

        Returns:
            ParsedContent with pages and flattened ordered blocks.

        Raises:
            InvalidFileFormatError: If first bytes are not %PDF-.
            FileTooLargeError: If file exceeds configured max size.
            CT200TimeoutError: If parsing exceeds wall-clock timeout.
            PathologicalInputError: If nesting > 20 levels or page > 50MB.
            ParsingError: For other unexpected parsing failures.
        """
        self._validate_input(pdf_bytes, filename)

        log = logger.bind(filename=filename, size_bytes=len(pdf_bytes))
        log.info("pdf_parse_start")

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._extract_content, pdf_bytes, filename),
                timeout=self._timeout_seconds,
            )
            log.info(
                "pdf_parse_complete",
                total_pages=result.total_pages,
                total_blocks=len(result.blocks),
            )
            return result
        except asyncio.TimeoutError:
            raise CT200TimeoutError(
                f"PDF parsing exceeded {self._timeout_seconds}s timeout",
                details={"filename": filename, "timeout_seconds": self._timeout_seconds},
            )
        except (
            CT200TimeoutError,
            PathologicalInputError,
            InvalidFileFormatError,
            FileTooLargeError,
        ):
            raise
        except Exception as exc:
            log.error("pdf_parse_error", error=str(exc))
            raise ParsingError(
                f"Unexpected error parsing PDF: {exc}",
                details={"filename": filename},
            ) from exc

    def _validate_input(self, pdf_bytes: bytes, filename: str) -> None:
        """Validate file size and magic bytes before parsing.

        Args:
            pdf_bytes: Raw PDF bytes.
            filename: For error context.

        Raises:
            FileTooLargeError: If file exceeds max size.
            InvalidFileFormatError: If magic bytes don't match %PDF-.
        """
        if len(pdf_bytes) > self._max_file_size:
            raise FileTooLargeError(
                f"File exceeds {self._max_file_size // (1024 * 1024)}MB limit",
                details={"filename": filename, "size_bytes": len(pdf_bytes)},
            )
        if not pdf_bytes[:5] == PDF_MAGIC_BYTES:
            raise InvalidFileFormatError(
                "File is not a valid PDF (magic-byte check failed)",
                details={"filename": filename},
            )

    def _extract_content(self, pdf_bytes: bytes, filename: str) -> ParsedContent:
        """Extract structured content from PDF bytes (runs in thread).

        Iterates pages, extracts text blocks and tables, applies multi-column
        sorting, and returns the complete ParsedContent.
        """
        start_time = time.perf_counter()

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            # Check outline nesting depth for pathological input
            toc = doc.get_toc(simple=True)
            if toc:
                max_depth = max(entry[0] for entry in toc)
                if max_depth > MAX_NESTING_DEPTH:
                    raise PathologicalInputError(
                        f"Document outline nesting depth ({max_depth}) exceeds limit ({MAX_NESTING_DEPTH})",
                        details={"filename": filename, "max_depth": max_depth},
                    )

            total_pages = len(doc)
            pages: list[ParsedPage] = []
            all_blocks: list[ContentBlock] = []

            # Compute median font size across the document for heading detection
            median_font_size = self._compute_median_font_size(doc, start_time)

            for page_idx in range(total_pages):
                # Check for timeout inside loop
                elapsed = time.perf_counter() - start_time
                if elapsed > self._timeout_seconds:
                    raise CT200TimeoutError(
                        f"Parsing exceeded timeout at page {page_idx + 1}",
                        details={"filename": filename, "page": page_idx + 1},
                    )

                page = doc[page_idx]

                # Check for pathological page content size
                page_text = page.get_text("text")
                if len(page_text.encode("utf-8")) > MAX_PAGE_CONTENT_BYTES:
                    raise PathologicalInputError(
                        f"Page {page_idx + 1} exceeds content size limit",
                        details={"filename": filename, "page": page_idx + 1},
                    )

                page_blocks = self._extract_page_blocks(page, page_idx + 1, median_font_size)
                parsed_page = ParsedPage(
                    page_number=page_idx + 1,
                    blocks=page_blocks,
                    raw_text=page_text,
                )
                pages.append(parsed_page)
                all_blocks.extend(page_blocks)

            content = ParsedContent(
                filename=filename,
                total_pages=total_pages,
                pages=pages,
                blocks=all_blocks,
            )

            # Strip repeated headers/footers from extracted content
            page_height = float(doc[0].rect.height) if total_pages > 0 else 842.0
            content, _stripped_count = strip_headers_footers(content, page_height)

            return content
        finally:
            doc.close()

    def _compute_median_font_size(self, doc: fitz.Document, start_time: float) -> float:
        """Sample font sizes from the document to determine the body text baseline.

        Returns the median font size, used as a reference for heading detection.
        """
        font_sizes: list[float] = []
        # Sample up to 10 pages for efficiency
        sample_pages = min(len(doc), 10)
        for page_idx in range(sample_pages):
            elapsed = time.perf_counter() - start_time
            if elapsed > self._timeout_seconds:
                break
            page = doc[page_idx]
            page_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        if text:
                            font_sizes.append(span.get("size", 12.0))

        if not font_sizes:
            return 12.0

        font_sizes.sort()
        mid = len(font_sizes) // 2
        return font_sizes[mid]

    def _extract_page_blocks(
        self, page: fitz.Page, page_number: int, median_font_size: float
    ) -> list[ContentBlock]:
        """Extract and classify content blocks from a single page.

        Handles text blocks via font heuristics, extracts tables via PyMuPDF's
        find_tables(), and applies multi-column sort order.
        """
        text_blocks: list[ContentBlock] = []
        table_bboxes: list[tuple[float, float, float, float]] = []

        # Try extracting tables first to know which regions to skip in text extraction
        table_blocks: list[ContentBlock] = []
        try:
            tables = page.find_tables()
            if tables and tables.tables:
                for table in tables.tables:
                    table_content = self._extract_table(table, page_number)
                    if table_content:
                        table_blocks.append(table_content)
                        if table_content.bbox:
                            table_bboxes.append(table_content.bbox)
        except Exception:
            # Table extraction is best-effort
            pass

        # Get text blocks with position information using "dict" output
        page_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

        # Detect columns using block x-coordinates
        page_width = page.rect.width
        columns = self._detect_columns(page_dict.get("blocks", []), page_width)

        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:  # only text blocks
                continue

            block_bbox = (
                block["bbox"][0],
                block["bbox"][1],
                block["bbox"][2],
                block["bbox"][3],
            )

            # Skip blocks that overlap with detected tables
            if self._overlaps_table(block_bbox, table_bboxes):
                continue

            block_content = self._process_text_block(
                block, page_number, median_font_size, columns
            )
            if block_content:
                text_blocks.extend(block_content)

        # Combine text blocks and table blocks
        all_blocks = text_blocks + table_blocks

        # Sort blocks by multi-column reading order:
        # Assign column index, then sort by column, then y-position, then x-position
        all_blocks.sort(key=lambda b: self._sort_key(b, columns))

        return all_blocks

    def _detect_columns(
        self, blocks: list[dict[str, Any]], page_width: float
    ) -> list[tuple[float, float]]:
        """Detect column boundaries from text block x-coordinates.

        Uses clustering of block left-edge x-coordinates to identify columns.
        Returns sorted list of (x_start, x_end) tuples for each detected column.
        """
        if not blocks:
            return [(0.0, page_width)]

        # Collect left edges of text blocks
        left_edges: list[float] = []
        for block in blocks:
            if block.get("type") != 0:
                continue
            left_edges.append(block["bbox"][0])

        if not left_edges:
            return [(0.0, page_width)]

        # Simple column detection: cluster left edges
        left_edges.sort()
        clusters: list[list[float]] = []
        threshold = page_width * 0.1  # 10% of page width as gap threshold

        current_cluster: list[float] = [left_edges[0]]
        for edge in left_edges[1:]:
            if edge - current_cluster[-1] > threshold:
                clusters.append(current_cluster)
                current_cluster = [edge]
            else:
                current_cluster.append(edge)
        clusters.append(current_cluster)

        # Build column ranges
        columns: list[tuple[float, float]] = []
        for i, cluster in enumerate(clusters):
            x_start = min(cluster)
            if i + 1 < len(clusters):
                x_end = min(clusters[i + 1]) - 1.0
            else:
                x_end = page_width
            columns.append((x_start, x_end))

        return columns

    def _sort_key(
        self, block: ContentBlock, columns: list[tuple[float, float]]
    ) -> tuple[int, float, float]:
        """Generate sort key for reading order: column index, y-position, x-position."""
        if not block.bbox:
            return (0, 0.0, 0.0)

        x0, y0 = block.bbox[0], block.bbox[1]
        col_idx = 0
        for i, (col_start, col_end) in enumerate(columns):
            if col_start <= x0 <= col_end:
                col_idx = i
                break

        return (col_idx, y0, x0)

    def _overlaps_table(
        self,
        block_bbox: tuple[float, float, float, float],
        table_bboxes: list[tuple[float, float, float, float]],
    ) -> bool:
        """Check if a text block significantly overlaps with any detected table region."""
        bx0, by0, bx1, by1 = block_bbox
        for tx0, ty0, tx1, ty1 in table_bboxes:
            # Check for overlap
            overlap_x = max(0.0, min(bx1, tx1) - max(bx0, tx0))
            overlap_y = max(0.0, min(by1, ty1) - max(by0, ty0))
            overlap_area = overlap_x * overlap_y
            block_area = (bx1 - bx0) * (by1 - by0)
            if block_area > 0 and overlap_area / block_area > 0.5:
                return True
        return False

    def _process_text_block(
        self,
        block: dict[str, Any],
        page_number: int,
        median_font_size: float,
        columns: list[tuple[float, float]],
    ) -> list[ContentBlock]:
        """Process a text block, classifying lines as heading, list item, or body."""
        results: list[ContentBlock] = []
        block_bbox = (
            block["bbox"][0],
            block["bbox"][1],
            block["bbox"][2],
            block["bbox"][3],
        )

        for line in block.get("lines", []):
            text_parts: list[str] = []
            max_font_size = 0.0
            is_bold = False
            total_chars = 0

            for span in line.get("spans", []):
                span_text = span.get("text", "")
                text_parts.append(span_text)
                font_size = span.get("size", 12.0)
                max_font_size = max(max_font_size, font_size)
                font_name = span.get("font", "").lower()
                if "bold" in font_name or "heavy" in font_name or "black" in font_name:
                    is_bold = True
                total_chars += len(span_text.strip())

            text = "".join(text_parts).strip()
            if not text:
                continue

            # Use line-level bounding box if available, otherwise block bbox
            line_bbox = block_bbox
            if "bbox" in line:
                line_bbox = (
                    line["bbox"][0],
                    line["bbox"][1],
                    line["bbox"][2],
                    line["bbox"][3],
                )

            # Classify the line
            block_type, level = self._classify_line(
                text, max_font_size, is_bold, median_font_size
            )

            results.append(
                ContentBlock(
                    block_type=block_type,
                    content=text,
                    page_number=page_number,
                    level=level,
                    bbox=line_bbox,
                )
            )

        return results

    def _classify_line(
        self,
        text: str,
        font_size: float,
        is_bold: bool,
        median_font_size: float,
    ) -> tuple[BlockType, int]:
        """Classify a text line as heading, list item, or body text.

        Uses font size relative to the document median and bold formatting
        to determine heading levels. Falls back to pattern matching for lists.
        """
        # List item detection takes precedence for numbered/bulleted items
        for pattern in _LIST_PATTERNS:
            if pattern.match(text):
                return BlockType.LIST_ITEM, 0

        # Heading detection: compare font size to median
        size_ratio = font_size / median_font_size if median_font_size > 0 else 1.0

        # Level 1: significantly larger and bold
        if size_ratio >= 1.6 and is_bold:
            return BlockType.HEADING, 1
        # Level 2: larger and bold
        if size_ratio >= 1.35 and is_bold:
            return BlockType.HEADING, 2
        # Level 3: somewhat larger and bold, or large without bold
        if size_ratio >= 1.15 and is_bold and len(text) < 120:
            return BlockType.HEADING, 3
        # Level 4: bold at body size with short text (likely a sub-heading)
        if is_bold and len(text) < 80 and size_ratio >= 1.0:
            return BlockType.HEADING, 4
        # Level 5: larger font without bold, short text
        if size_ratio >= 1.3 and not is_bold and len(text) < 100:
            return BlockType.HEADING, 5

        return BlockType.BODY, 0

    def _extract_table(
        self, table: Any, page_number: int
    ) -> ContentBlock | None:
        """Extract a table as a markdown-formatted content block.

        Args:
            table: A PyMuPDF Table object.
            page_number: 1-based page number.

        Returns:
            ContentBlock with TABLE type and markdown content, or None if empty.
        """
        try:
            rows = table.extract()
            if not rows:
                return None

            # Filter out completely empty rows
            non_empty_rows = [
                row for row in rows if any(cell and str(cell).strip() for cell in row)
            ]
            if not non_empty_rows:
                return None

            # Build markdown table
            lines: list[str] = []
            for i, row in enumerate(non_empty_rows):
                cells = [str(cell).strip() if cell else "" for cell in row]
                lines.append("| " + " | ".join(cells) + " |")
                if i == 0:
                    lines.append("| " + " | ".join(["---"] * len(cells)) + " |")

            content = "\n".join(lines)
            bbox_rect = table.bbox
            bbox = (
                (float(bbox_rect[0]), float(bbox_rect[1]), float(bbox_rect[2]), float(bbox_rect[3]))
                if bbox_rect
                else None
            )

            return ContentBlock(
                block_type=BlockType.TABLE,
                content=content,
                page_number=page_number,
                level=0,
                bbox=bbox,
            )
        except Exception as exc:
            logger.debug("table_extraction_failed", page=page_number, error=str(exc))
            return None
