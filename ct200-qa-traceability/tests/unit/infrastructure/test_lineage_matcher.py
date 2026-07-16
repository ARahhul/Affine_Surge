"""Unit tests for the three-tier lineage matcher.

Tests CP-5.1 (strategy ordering), CP-5.2 (needs_review flagging),
and general matching behaviour across tiers.
"""

import pytest

from ct200.domain.entities import (
    DocumentNode,
    DocumentTree,
    LineageStatus,
    MatchStrategy,
)
from ct200.infrastructure.versioning.lineage_matcher import LineageMatcher


# --- Helpers ---


def _node(
    id: str,
    version_id: str = "v1",
    heading: str = "",
    body: str = "",
    depth: int = 0,
    order_index: int = 0,
    lineage_id: str = "",
    content_hash: str = "",
) -> DocumentNode:
    return DocumentNode(
        id=id,
        version_id=version_id,
        heading=heading,
        body=body,
        depth=depth,
        order_index=order_index,
        lineage_id=lineage_id or id,
        content_hash=content_hash or f"hash-{id}",
    )


def _tree(root: DocumentNode) -> DocumentTree:
    count = len(_flatten(root))
    max_d = max(n.depth for n in _flatten(root))
    return DocumentTree(root=root, node_count=count, max_depth=max_d)


def _flatten(node: DocumentNode) -> list[DocumentNode]:
    result = [node]
    for child in node.children:
        result.extend(_flatten(child))
    return result


# --- Tests: First Version ---


class TestFirstVersion:
    """When prev_tree is None, all nodes should be marked NEW."""

    def test_all_nodes_new(self):
        root = _node("r", heading="Root", depth=0)
        child = _node("c1", heading="Ch1", depth=1, order_index=0)
        root.children = [child]
        tree = _tree(root)

        matcher = LineageMatcher(confidence_threshold=0.75)
        matches = matcher.match_lineage(tree, None)

        assert len(matches) == 2
        for m in matches:
            assert m.strategy == MatchStrategy.NEW
            assert m.status == LineageStatus.NEW
            assert m.confidence == 1.0


# --- Tests: Tier 1 - Exact Hash Match ---


class TestExactHashMatch:
    """Tier 1: Exact content hash produces confidence 1.0 and MATCHED status."""

    def test_identical_hash_matched(self):
        prev_root = _node("pr", heading="Root", depth=0, content_hash="SAME_HASH", lineage_id="lin-root")
        prev_tree = _tree(prev_root)

        new_root = _node("nr", version_id="v2", heading="Root", depth=0, content_hash="SAME_HASH")
        new_tree = _tree(new_root)

        matcher = LineageMatcher(confidence_threshold=0.75)
        matches = matcher.match_lineage(new_tree, prev_tree)

        assert len(matches) == 1
        assert matches[0].strategy == MatchStrategy.EXACT
        assert matches[0].confidence == 1.0
        assert matches[0].status == LineageStatus.MATCHED
        assert matches[0].lineage_id == "lin-root"

    def test_exact_match_takes_priority_over_heading(self):
        """CP-5.1: Even if heading also matches, exact hash wins."""
        prev_root = _node(
            "pr", heading="Same Heading", depth=0,
            content_hash="EXACT", lineage_id="lin-prev"
        )
        prev_tree = _tree(prev_root)

        new_root = _node(
            "nr", version_id="v2", heading="Same Heading", depth=0,
            content_hash="EXACT"
        )
        new_tree = _tree(new_root)

        matcher = LineageMatcher(confidence_threshold=0.75)
        matches = matcher.match_lineage(new_tree, prev_tree)

        assert matches[0].strategy == MatchStrategy.EXACT


# --- Tests: Tier 2 - Heading Match ---


class TestHeadingMatch:
    """Tier 2: Same heading with different hash uses heading strategy."""

    def test_heading_match_with_depth_and_position(self):
        prev_root = _node(
            "pr", heading="Chapter One", depth=1, order_index=0,
            content_hash="hash-old", lineage_id="lin-ch1"
        )
        prev_tree = _tree(prev_root)

        new_root = _node(
            "nr", version_id="v2", heading="Chapter One", depth=1, order_index=0,
            content_hash="hash-new"
        )
        new_tree = _tree(new_root)

        matcher = LineageMatcher(confidence_threshold=0.75)
        matches = matcher.match_lineage(new_tree, prev_tree)

        assert matches[0].strategy == MatchStrategy.HEADING
        assert matches[0].lineage_id == "lin-ch1"
        # Same depth + close position → 0.8 + 0.1 + 0.05 = 0.95
        assert matches[0].confidence == 0.95
        assert matches[0].status == LineageStatus.MATCHED

    def test_heading_match_different_depth_lowers_confidence(self):
        prev_root = _node(
            "pr", heading="Section", depth=1, order_index=0,
            content_hash="h-old", lineage_id="lin-s"
        )
        prev_tree = _tree(prev_root)

        new_root = _node(
            "nr", version_id="v2", heading="Section", depth=3, order_index=5,
            content_hash="h-new"
        )
        new_tree = _tree(new_root)

        matcher = LineageMatcher(confidence_threshold=0.75)
        matches = matcher.match_lineage(new_tree, prev_tree)

        assert matches[0].strategy == MatchStrategy.HEADING
        # Different depth, far position → base 0.8 only
        assert matches[0].confidence == 0.8
        assert matches[0].status == LineageStatus.MATCHED

    def test_empty_heading_does_not_match(self):
        """Empty headings should not produce heading matches."""
        prev_root = _node("pr", heading="", depth=0, content_hash="h1", lineage_id="l1")
        prev_tree = _tree(prev_root)

        new_root = _node("nr", version_id="v2", heading="", depth=0, content_hash="h2")
        new_tree = _tree(new_root)

        matcher = LineageMatcher(confidence_threshold=0.75)
        matches = matcher.match_lineage(new_tree, prev_tree)

        # Should fall through to positional or new
        assert matches[0].strategy in (MatchStrategy.POSITIONAL, MatchStrategy.NEW)


# --- Tests: Tier 3 - Positional Fallback ---


class TestPositionalFallback:
    """Tier 3: When neither hash nor heading match, use positional."""

    def test_positional_match_same_depth(self):
        prev_root = _node(
            "pr", heading="Old Title", depth=1, order_index=0,
            content_hash="h-old", lineage_id="lin-pos"
        )
        prev_tree = _tree(prev_root)

        new_root = _node(
            "nr", version_id="v2", heading="Completely Different", depth=1, order_index=0,
            content_hash="h-new"
        )
        new_tree = _tree(new_root)

        matcher = LineageMatcher(confidence_threshold=0.75)
        matches = matcher.match_lineage(new_tree, prev_tree)

        assert matches[0].strategy == MatchStrategy.POSITIONAL
        assert matches[0].lineage_id == "lin-pos"
        # Same order_index → 0.5 + 0.15 = 0.65 (no word overlap)
        assert matches[0].confidence == 0.65
        # Below 0.75 threshold → needs_review
        assert matches[0].status == LineageStatus.NEEDS_REVIEW

    def test_positional_different_depth_no_match(self):
        """Positional only matches nodes at the same depth."""
        prev_root = _node(
            "pr", heading="Deep Node", depth=3, order_index=0,
            content_hash="h-old", lineage_id="lin-deep"
        )
        prev_tree = _tree(prev_root)

        new_root = _node(
            "nr", version_id="v2", heading="Shallow Node", depth=1, order_index=0,
            content_hash="h-new"
        )
        new_tree = _tree(new_root)

        matcher = LineageMatcher(confidence_threshold=0.75)
        matches = matcher.match_lineage(new_tree, prev_tree)

        # Different depths → no positional match → NEW
        assert matches[0].strategy == MatchStrategy.NEW


# --- Tests: CP-5.2 Needs Review Flagging ---


class TestNeedsReviewFlagging:
    """CP-5.2: Low-confidence matches must be flagged needs_review."""

    def test_below_threshold_gets_needs_review(self):
        prev_root = _node(
            "pr", heading="X", depth=1, order_index=0,
            content_hash="old", lineage_id="lin-x"
        )
        prev_tree = _tree(prev_root)

        new_root = _node(
            "nr", version_id="v2", heading="Y", depth=1, order_index=3,
            content_hash="new"
        )
        new_tree = _tree(new_root)

        # Positional match at same depth → confidence likely 0.5
        matcher = LineageMatcher(confidence_threshold=0.75)
        matches = matcher.match_lineage(new_tree, prev_tree)

        assert matches[0].status == LineageStatus.NEEDS_REVIEW
        assert matches[0].confidence < 0.75

    def test_above_threshold_gets_matched(self):
        """With a very low threshold, same match should be accepted."""
        prev_root = _node(
            "pr", heading="X", depth=1, order_index=0,
            content_hash="old", lineage_id="lin-x"
        )
        prev_tree = _tree(prev_root)

        new_root = _node(
            "nr", version_id="v2", heading="Y", depth=1, order_index=3,
            content_hash="new"
        )
        new_tree = _tree(new_root)

        matcher = LineageMatcher(confidence_threshold=0.1)
        matches = matcher.match_lineage(new_tree, prev_tree)

        assert matches[0].status == LineageStatus.MATCHED

    def test_exact_match_never_needs_review(self):
        """Exact matches always have confidence 1.0 — never needs_review."""
        prev_root = _node("pr", heading="H", depth=0, content_hash="SAME", lineage_id="l")
        prev_tree = _tree(prev_root)

        new_root = _node("nr", version_id="v2", heading="H", depth=0, content_hash="SAME")
        new_tree = _tree(new_root)

        # Even with threshold 1.0, exact match (confidence=1.0) passes
        matcher = LineageMatcher(confidence_threshold=1.0)
        matches = matcher.match_lineage(new_tree, prev_tree)

        assert matches[0].strategy == MatchStrategy.EXACT
        assert matches[0].status == LineageStatus.MATCHED


# --- Tests: Strategy Ordering (CP-5.1) ---


class TestStrategyOrdering:
    """CP-5.1: Strategies are tried in strict order: exact → heading → positional."""

    def test_hash_match_preferred_over_heading_match(self):
        """Node with both hash and heading match uses exact."""
        prev = _node("p", heading="Title", depth=0, content_hash="H1", lineage_id="l-p")
        prev_tree = _tree(prev)

        new = _node("n", version_id="v2", heading="Title", depth=0, content_hash="H1")
        new_tree = _tree(new)

        matcher = LineageMatcher(confidence_threshold=0.75)
        matches = matcher.match_lineage(new_tree, prev_tree)

        assert matches[0].strategy == MatchStrategy.EXACT

    def test_heading_preferred_over_positional(self):
        """Node with heading match but no hash match uses heading."""
        prev = _node("p", heading="Specific Title", depth=1, order_index=0,
                     content_hash="old-h", lineage_id="l-p")
        prev_tree = _tree(prev)

        new = _node("n", version_id="v2", heading="Specific Title", depth=1,
                    order_index=0, content_hash="new-h")
        new_tree = _tree(new)

        matcher = LineageMatcher(confidence_threshold=0.75)
        matches = matcher.match_lineage(new_tree, prev_tree)

        assert matches[0].strategy == MatchStrategy.HEADING
