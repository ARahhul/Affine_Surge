"""Unit tests for repeated header/footer detection and stripping."""

import pytest

from ct200.domain.entities import BlockType, ContentBlock, ParsedContent, ParsedPage
from ct200.infrastructure.parser.header_footer_stripper import (
    TOP_MARGIN_FRACTION,
    BOTTOM_MARGIN_FRACTION,
    strip_headers_footers,
    _find_consecutive_repeats,
)


PAGE_HEIGHT = 842.0  # A4 default


def _make_block(
    content: str,
    page_number: int,
    y_pos: float,
    block_type: BlockType = BlockType.BODY,
) -> ContentBlock:
    """Create a content block with a given y-position."""
    return ContentBlock(
        block_type=block_type,
        content=content,
        page_number=page_number,
        level=0,
        bbox=(50.0, y_pos, 500.0, y_pos + 12.0),
    )


def _make_content(pages_data: list[list[ContentBlock]], filename: str = "test.pdf") -> ParsedContent:
    """Build ParsedContent from a list of pages, each with a list of blocks."""
    pages = []
    all_blocks = []
    for i, blocks in enumerate(pages_data):
        page = ParsedPage(
            page_number=i + 1,
            blocks=blocks,
            raw_text=" ".join(b.content for b in blocks),
        )
        pages.append(page)
        all_blocks.extend(blocks)
    return ParsedContent(
        filename=filename,
        total_pages=len(pages),
        pages=pages,
        blocks=all_blocks,
    )


class TestStripHeadersFooters:
    """Tests for the strip_headers_footers function."""

    def test_single_page_returns_unchanged(self):
        """Single-page documents should never be modified."""
        block = _make_block("Header Text", 1, y_pos=10.0)
        content = _make_content([[block]])
        result, stripped = strip_headers_footers(content, PAGE_HEIGHT)
        assert stripped == 0
        assert len(result.blocks) == 1

    def test_strips_header_repeated_on_consecutive_pages(self):
        """Header text appearing on 2+ consecutive pages in top margin gets stripped."""
        top_y = PAGE_HEIGHT * TOP_MARGIN_FRACTION * 0.5  # Well within top margin
        body_y = PAGE_HEIGHT * 0.5  # Middle of page

        pages_data = [
            [
                _make_block("CT200 Technical Manual", 1, y_pos=top_y),
                _make_block("Chapter 1 content here", 1, y_pos=body_y),
            ],
            [
                _make_block("CT200 Technical Manual", 2, y_pos=top_y),
                _make_block("Chapter 2 content here", 2, y_pos=body_y),
            ],
            [
                _make_block("CT200 Technical Manual", 3, y_pos=top_y),
                _make_block("Chapter 3 content here", 3, y_pos=body_y),
            ],
        ]
        content = _make_content(pages_data)
        result, stripped = strip_headers_footers(content, PAGE_HEIGHT)

        assert stripped == 3
        # Only body content should remain
        for page in result.pages:
            for block in page.blocks:
                assert "ct200 technical manual" not in block.content.lower()

    def test_strips_footer_repeated_on_consecutive_pages(self):
        """Footer text in bottom margin on 2+ consecutive pages gets stripped."""
        body_y = PAGE_HEIGHT * 0.5
        bottom_y = PAGE_HEIGHT * BOTTOM_MARGIN_FRACTION + 10.0  # In bottom margin

        pages_data = [
            [
                _make_block("Page content 1", 1, y_pos=body_y),
                _make_block("Page 1", 1, y_pos=bottom_y),
            ],
            [
                _make_block("Page content 2", 2, y_pos=body_y),
                _make_block("Page 2", 2, y_pos=bottom_y),
            ],
        ]
        content = _make_content(pages_data)
        result, stripped = strip_headers_footers(content, PAGE_HEIGHT)

        # "Page 1" and "Page 2" are different text so NOT stripped
        assert stripped == 0

    def test_strips_identical_footer_on_consecutive_pages(self):
        """Identical footer text on consecutive pages gets stripped."""
        body_y = PAGE_HEIGHT * 0.5
        bottom_y = PAGE_HEIGHT * BOTTOM_MARGIN_FRACTION + 10.0

        pages_data = [
            [
                _make_block("Page content 1", 1, y_pos=body_y),
                _make_block("© 2024 Company Inc.", 1, y_pos=bottom_y),
            ],
            [
                _make_block("Page content 2", 2, y_pos=body_y),
                _make_block("© 2024 Company Inc.", 2, y_pos=bottom_y),
            ],
        ]
        content = _make_content(pages_data)
        result, stripped = strip_headers_footers(content, PAGE_HEIGHT)

        assert stripped == 2
        for page in result.pages:
            for block in page.blocks:
                assert "company inc" not in block.content.lower()

    def test_preserves_unique_content(self):
        """Content that does not repeat on consecutive pages is preserved."""
        top_y = PAGE_HEIGHT * TOP_MARGIN_FRACTION * 0.5
        body_y = PAGE_HEIGHT * 0.5

        pages_data = [
            [
                _make_block("Unique Header Page 1", 1, y_pos=top_y),
                _make_block("Body text page 1", 1, y_pos=body_y),
            ],
            [
                _make_block("Different Header Page 2", 2, y_pos=top_y),
                _make_block("Body text page 2", 2, y_pos=body_y),
            ],
        ]
        content = _make_content(pages_data)
        result, stripped = strip_headers_footers(content, PAGE_HEIGHT)

        assert stripped == 0
        assert len(result.blocks) == 4

    def test_no_stripping_for_mid_page_content(self):
        """Content in the middle of the page is never stripped even if repeated."""
        body_y = PAGE_HEIGHT * 0.5

        pages_data = [
            [_make_block("Repeated body text", 1, y_pos=body_y)],
            [_make_block("Repeated body text", 2, y_pos=body_y)],
            [_make_block("Repeated body text", 3, y_pos=body_y)],
        ]
        content = _make_content(pages_data)
        result, stripped = strip_headers_footers(content, PAGE_HEIGHT)

        assert stripped == 0
        assert len(result.blocks) == 3

    def test_blocks_without_bbox_are_preserved(self):
        """Blocks without bounding box info are not considered for stripping."""
        block_no_bbox = ContentBlock(
            block_type=BlockType.BODY,
            content="No bbox block",
            page_number=1,
            level=0,
            bbox=None,
        )
        pages_data = [
            [block_no_bbox],
            [
                ContentBlock(
                    block_type=BlockType.BODY,
                    content="No bbox block",
                    page_number=2,
                    level=0,
                    bbox=None,
                )
            ],
        ]
        content = _make_content(pages_data)
        result, stripped = strip_headers_footers(content, PAGE_HEIGHT)

        assert stripped == 0
        assert len(result.blocks) == 2

    def test_case_insensitive_matching(self):
        """Header detection is case-insensitive."""
        top_y = PAGE_HEIGHT * TOP_MARGIN_FRACTION * 0.5

        pages_data = [
            [_make_block("CT200 MANUAL", 1, y_pos=top_y)],
            [_make_block("ct200 manual", 2, y_pos=top_y)],
            [_make_block("CT200 Manual", 3, y_pos=top_y)],
        ]
        content = _make_content(pages_data)
        result, stripped = strip_headers_footers(content, PAGE_HEIGHT)

        assert stripped == 3
        assert len(result.blocks) == 0

    def test_non_consecutive_repeats_not_stripped(self):
        """Text that repeats but not on consecutive pages is not stripped."""
        top_y = PAGE_HEIGHT * TOP_MARGIN_FRACTION * 0.5
        body_y = PAGE_HEIGHT * 0.5

        pages_data = [
            [_make_block("Header A", 1, y_pos=top_y)],
            [_make_block("Different text", 2, y_pos=body_y)],
            [_make_block("Header A", 3, y_pos=top_y)],
        ]
        content = _make_content(pages_data)
        result, stripped = strip_headers_footers(content, PAGE_HEIGHT)

        assert stripped == 0


class TestFindConsecutiveRepeats:
    """Tests for the _find_consecutive_repeats helper."""

    def test_empty_pages(self):
        """Empty input returns empty set."""
        result = _find_consecutive_repeats({}, 0)
        assert result == set()

    def test_text_on_single_page(self):
        """Text appearing on only one page is not repeated."""
        result = _find_consecutive_repeats({1: ["hello"], 2: ["world"]}, 2)
        assert result == set()

    def test_consecutive_repeat(self):
        """Text on two consecutive pages is detected."""
        texts_by_page = {1: ["header"], 2: ["header"], 3: []}
        result = _find_consecutive_repeats(texts_by_page, 3)
        assert "header" in result

    def test_gap_breaks_consecutive(self):
        """Text with a gap page is not counted as consecutive."""
        texts_by_page = {1: ["header"], 2: [], 3: ["header"]}
        result = _find_consecutive_repeats(texts_by_page, 3)
        assert result == set()
