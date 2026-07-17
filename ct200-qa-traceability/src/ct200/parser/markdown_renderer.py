"""Markdown renderer for reconstructing document content from parsed blocks.

Produces deterministic markdown output from ParsedContent — same input always
produces byte-identical output. Handles headings, tables, lists, and body text.
"""

import re

from ct200.models import BlockType, ContentBlock, ParsedContent


def render_markdown(content: ParsedContent) -> str:
    """Render parsed content to markdown string.

    Produces a deterministic markdown reconstruction from the ordered
    content blocks. Handles heading levels, tables (already in markdown),
    list items, and body paragraphs.

    Args:
        content: ParsedContent with ordered blocks.

    Returns:
        Markdown string representation of the document.
    """
    lines: list[str] = []
    prev_type: BlockType | None = None

    for block in content.blocks:
        # Add spacing between different block types
        if prev_type is not None and _needs_blank_line(prev_type, block.block_type):
            lines.append("")

        rendered = _render_block(block)
        if rendered:
            lines.append(rendered)

        prev_type = block.block_type

    # Ensure trailing newline for file compatibility
    result = "\n".join(lines)
    if result and not result.endswith("\n"):
        result += "\n"

    return result


def _render_block(block: ContentBlock) -> str:
    """Render a single content block to markdown."""
    match block.block_type:
        case BlockType.HEADING:
            prefix = "#" * max(1, min(block.level, 6))
            return f"{prefix} {block.content}"

        case BlockType.TABLE:
            # Tables are already in markdown format from the parser
            return block.content

        case BlockType.LIST_ITEM:
            # Preserve original numbering/bullet from content if already formatted
            if _is_already_formatted_list(block.content):
                return block.content
            return f"- {block.content}"

        case BlockType.BODY:
            return block.content

        case _:
            return block.content


def _needs_blank_line(prev_type: BlockType, curr_type: BlockType) -> bool:
    """Determine if a blank line is needed between two block types.

    Rules (applied in order):
    - Always blank line before/after headings
    - Always blank line before/after tables
    - Blank line between body paragraphs
    - No blank line between consecutive list items
    - Blank line transitioning to/from list blocks
    """
    # Always blank line before/after headings
    if curr_type == BlockType.HEADING or prev_type == BlockType.HEADING:
        return True
    # Blank line before/after tables
    if curr_type == BlockType.TABLE or prev_type == BlockType.TABLE:
        return True
    # Blank line between body paragraphs
    if prev_type == BlockType.BODY and curr_type == BlockType.BODY:
        return True
    # No blank line between consecutive list items
    if prev_type == BlockType.LIST_ITEM and curr_type == BlockType.LIST_ITEM:
        return False
    # Blank line transitioning to/from list
    if prev_type == BlockType.LIST_ITEM and curr_type != BlockType.LIST_ITEM:
        return True
    return prev_type != BlockType.LIST_ITEM and curr_type == BlockType.LIST_ITEM


# Pre-compiled patterns for detecting already-formatted list items
_FORMATTED_LIST_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\d+\."),  # "1." or "1.1"
    re.compile(r"^[a-z]\)"),  # "a)"
    re.compile(r"^[A-Z]\)"),  # "A)"
    re.compile(r"^[•●○▪▸►◦–—-]"),  # bullets/dashes
]


def _is_already_formatted_list(text: str) -> bool:
    """Check if the text already has list formatting (numbered or bulleted)."""
    return any(pattern.match(text) for pattern in _FORMATTED_LIST_PATTERNS)
