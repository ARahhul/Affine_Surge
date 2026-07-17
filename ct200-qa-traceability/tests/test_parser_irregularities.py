"""Test parser tree engine handles irregularities correctly.

Verifies:
- Duplicate headings yield separate node IDs with correct parents
- Skipped heading levels (H2 → H4) insert at correct structural depth
- Numbered list items are NOT promoted to heading nodes
- Document ordering is preserved regardless of source numbering
"""

import os
import sys

os.environ.setdefault("NVIDIA_NIM_API_KEY", "test")
os.environ.setdefault("AUTH_SECRET_KEY", "test")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ct200.models import BlockType, ContentBlock, ParsedContent, ParsedPage
from ct200.parser.tree_engine import TreeEngine


def _make_content(blocks: list[ContentBlock]) -> ParsedContent:
    return ParsedContent(
        filename="test.pdf",
        total_pages=1,
        pages=[ParsedPage(page_number=1, blocks=blocks)],
        blocks=blocks,
    )


class TestDuplicateHeadings:
    """Duplicate heading text must produce separate nodes with distinct IDs."""

    def test_same_heading_text_yields_distinct_nodes(self):
        blocks = [
            ContentBlock(
                block_type=BlockType.HEADING, content="Introduction", page_number=1, level=1
            ),
            ContentBlock(block_type=BlockType.BODY, content="First section body", page_number=1),
            ContentBlock(
                block_type=BlockType.HEADING, content="Introduction", page_number=1, level=1
            ),
            ContentBlock(block_type=BlockType.BODY, content="Second section body", page_number=1),
        ]
        tree = TreeEngine().build_tree(_make_content(blocks))
        # Root + 2 children with same heading text
        children = tree.root.children
        assert len(children) == 2
        assert children[0].heading == children[1].heading == "Introduction"
        assert children[0].id != children[1].id
        assert children[0].parent_id == children[1].parent_id == tree.root.id

    def test_duplicate_headings_at_different_levels(self):
        blocks = [
            ContentBlock(block_type=BlockType.HEADING, content="Safety", page_number=1, level=1),
            ContentBlock(block_type=BlockType.HEADING, content="Safety", page_number=1, level=2),
        ]
        tree = TreeEngine().build_tree(_make_content(blocks))
        top = tree.root.children[0]
        nested = top.children[0]
        assert top.heading == nested.heading == "Safety"
        assert nested.parent_id == top.id
        assert top.depth == 1
        assert nested.depth == 2


class TestSkippedHeadingLevels:
    """H2 jumping directly to H4 must still produce valid parent-child depth."""

    def test_h2_to_h4_skip(self):
        blocks = [
            ContentBlock(block_type=BlockType.HEADING, content="Chapter", page_number=1, level=1),
            ContentBlock(block_type=BlockType.HEADING, content="Section", page_number=1, level=2),
            ContentBlock(block_type=BlockType.HEADING, content="Deep Sub", page_number=1, level=4),
        ]
        tree = TreeEngine().build_tree(_make_content(blocks))
        chapter = tree.root.children[0]
        section = chapter.children[0]
        deep = section.children[0]
        # Depth is always parent+1, not the raw heading level
        assert chapter.depth == 1
        assert section.depth == 2
        assert deep.depth == 3  # Corrected from raw level 4 to structural depth 3
        assert deep.parent_id == section.id

    def test_h1_to_h3_skip(self):
        blocks = [
            ContentBlock(block_type=BlockType.HEADING, content="Top", page_number=1, level=1),
            ContentBlock(block_type=BlockType.HEADING, content="Skipped", page_number=1, level=3),
        ]
        tree = TreeEngine().build_tree(_make_content(blocks))
        top = tree.root.children[0]
        skipped = top.children[0]
        assert skipped.depth == 2  # parent.depth + 1, not raw level
        assert skipped.parent_id == top.id


class TestListItemClassification:
    """Numbered list items must NOT become separate heading nodes."""

    def test_numbered_list_stays_in_body(self):
        blocks = [
            ContentBlock(
                block_type=BlockType.HEADING, content="Procedures", page_number=1, level=1
            ),
            ContentBlock(
                block_type=BlockType.LIST_ITEM, content="1. Turn off power", page_number=1
            ),
            ContentBlock(block_type=BlockType.LIST_ITEM, content="2. Remove cover", page_number=1),
        ]
        tree = TreeEngine().build_tree(_make_content(blocks))
        proc_node = tree.root.children[0]
        # List items become body content, not child nodes
        assert len(proc_node.children) == 0
        assert "Turn off power" in proc_node.body
        assert "Remove cover" in proc_node.body


class TestDocumentOrderPreservation:
    """Order index must reflect source document sequence."""

    def test_sibling_order_matches_source(self):
        blocks = [
            ContentBlock(block_type=BlockType.HEADING, content="C", page_number=1, level=1),
            ContentBlock(block_type=BlockType.HEADING, content="A", page_number=1, level=1),
            ContentBlock(block_type=BlockType.HEADING, content="B", page_number=1, level=1),
        ]
        tree = TreeEngine().build_tree(_make_content(blocks))
        children = tree.root.children
        assert children[0].heading == "C" and children[0].order_index == 0
        assert children[1].heading == "A" and children[1].order_index == 1
        assert children[2].heading == "B" and children[2].order_index == 2
