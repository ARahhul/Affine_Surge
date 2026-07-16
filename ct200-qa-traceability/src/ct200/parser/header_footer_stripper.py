"""Detect and strip repeated running headers/footers from parsed content.

Headers/footers are identified as text blocks that:
1. Appear on 2 or more consecutive pages
2. Have identical or near-identical text content
3. Are positioned at the top or bottom of the page (within margin zones)
"""

import structlog

from ct200.models import ContentBlock, ParsedContent, ParsedPage

logger = structlog.get_logger()

# Top/bottom margin zones as fraction of page height
TOP_MARGIN_FRACTION = 0.12  # top 12% of page
BOTTOM_MARGIN_FRACTION = 0.88  # bottom 12% of page


def strip_headers_footers(
    content: ParsedContent, page_height: float = 842.0
) -> tuple[ParsedContent, int]:
    """Strip repeated headers and footers from parsed content.

    Identifies text blocks that appear identically on 2+ consecutive pages
    in the top or bottom margin zones and removes them.

    Args:
        content: The parsed content to process.
        page_height: Default A4 page height in points (842).

    Returns:
        Tuple of (cleaned ParsedContent, count of stripped elements).
    """
    if content.total_pages < 2:
        return content, 0

    # Identify candidate repeated texts in margin zones
    top_texts_by_page: dict[int, list[str]] = {}
    bottom_texts_by_page: dict[int, list[str]] = {}

    top_threshold = page_height * TOP_MARGIN_FRACTION
    bottom_threshold = page_height * BOTTOM_MARGIN_FRACTION

    for page in content.pages:
        top_texts: list[str] = []
        bottom_texts: list[str] = []

        for block in page.blocks:
            if not block.bbox:
                continue
            y_pos = block.bbox[1]  # top edge of block
            text_normalized = block.content.strip().lower()
            if not text_normalized:
                continue

            if y_pos <= top_threshold:
                top_texts.append(text_normalized)
            elif y_pos >= bottom_threshold:
                bottom_texts.append(text_normalized)

        top_texts_by_page[page.page_number] = top_texts
        bottom_texts_by_page[page.page_number] = bottom_texts

    # Find texts appearing on 2+ consecutive pages
    repeated_texts: set[str] = set()

    # Check top margin
    repeated_texts.update(
        _find_consecutive_repeats(top_texts_by_page, content.total_pages)
    )
    # Check bottom margin
    repeated_texts.update(
        _find_consecutive_repeats(bottom_texts_by_page, content.total_pages)
    )

    if not repeated_texts:
        return content, 0

    # Strip the repeated elements
    stripped_count = 0
    new_pages: list[ParsedPage] = []
    new_all_blocks: list[ContentBlock] = []

    for page in content.pages:
        new_blocks: list[ContentBlock] = []
        for block in page.blocks:
            text_normalized = block.content.strip().lower()
            if text_normalized in repeated_texts:
                stripped_count += 1
            else:
                new_blocks.append(block)
                new_all_blocks.append(block)

        new_pages.append(
            ParsedPage(
                page_number=page.page_number,
                blocks=new_blocks,
                raw_text=page.raw_text,
            )
        )

    logger.info(
        "headers_footers_stripped",
        stripped_count=stripped_count,
        repeated_patterns=len(repeated_texts),
    )

    return (
        ParsedContent(
            filename=content.filename,
            total_pages=content.total_pages,
            pages=new_pages,
            blocks=new_all_blocks,
        ),
        stripped_count,
    )


def _find_consecutive_repeats(
    texts_by_page: dict[int, list[str]], total_pages: int
) -> set[str]:
    """Find texts appearing on 2+ consecutive pages."""
    all_texts: set[str] = set()
    for texts in texts_by_page.values():
        all_texts.update(texts)

    repeated: set[str] = set()

    for text in all_texts:
        consecutive = 0
        max_consecutive = 0
        for page_num in range(1, total_pages + 1):
            if text in texts_by_page.get(page_num, []):
                consecutive += 1
                max_consecutive = max(max_consecutive, consecutive)
            else:
                consecutive = 0

        if max_consecutive >= 2:
            repeated.add(text)

    return repeated
