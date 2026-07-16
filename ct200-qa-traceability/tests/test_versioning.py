"""Test versioning — lineage matching across document versions.

Verifies:
- Exact hash match produces confidence 1.0
- Heading-based match correctly identifies renamed/moved nodes
- Low-confidence matches are flagged needs_review
- Strategy ordering: exact → heading → positional (never skipped)
- First version marks all nodes as NEW
"""

import os
import sys

os.environ.setdefault("NVIDIA_NIM_API_KEY", "test")
os.environ.setdefault("AUTH_SECRET_KEY", "test")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ct200.versioning.lineage_matcher import LineageMatcher
from ct200.models import DocumentNode, DocumentTree


def _node(id, heading="", body="", depth=0, order_index=0,
          content_hash="", lineage_id="", version_id="v1"):
    return DocumentNode(
        id=id, version_id=version_id, heading=heading, body=body,
        depth=depth, order_index=order_index,
        content_hash=content_hash or f"hash-{id}",
        lineage_id=lineage_id or f"lin-{id}",
    )


def _tree(root):
    def _count(n):
        return 1 + sum(_count(c) for c in n.children)
    def _maxd(n):
        return n.depth if not n.children else max(_maxd(c) for c in n.children)
    return DocumentTree(root=root, node_count=_count(root), max_depth=_maxd(root))


class TestFirstVersionAllNew:
    def test_no_previous_marks_all_new(self):
        root = _node("r", heading="Root", depth=0)
        root.children = [_node("c1", heading="Ch1", depth=1, order_index=0)]
        matcher = LineageMatcher(confidence_threshold=0.75)
        matches = matcher.match_lineage(_tree(root), None)
        assert all(m.strategy.value == "new" for m in matches)


class TestExactHashMatch:
    def test_identical_content_matches_with_confidence_1(self):
        prev = _node("p", heading="X", content_hash="SAME", lineage_id="lin-prev")
        new = _node("n", heading="X", content_hash="SAME", version_id="v2")
        matcher = LineageMatcher(confidence_threshold=0.75)
        matches = matcher.match_lineage(_tree(new), _tree(prev))
        assert matches[0].strategy.value == "exact"
        assert matches[0].confidence == 1.0
        assert matches[0].lineage_id == "lin-prev"


class TestHeadingMatch:
    def test_same_heading_different_hash_uses_heading_strategy(self):
        prev = _node("p", heading="Safety Protocol", depth=1, order_index=0,
                     content_hash="old-hash", lineage_id="lin-safety")
        new = _node("n", heading="Safety Protocol", depth=1, order_index=0,
                    content_hash="new-hash", version_id="v2")
        matcher = LineageMatcher(confidence_threshold=0.75)
        matches = matcher.match_lineage(_tree(new), _tree(prev))
        assert matches[0].strategy.value == "heading"
        assert matches[0].lineage_id == "lin-safety"
        assert matches[0].confidence >= 0.8


class TestLowConfidenceNeedsReview:
    def test_positional_match_below_threshold_flagged(self):
        prev = _node("p", heading="Old Title", depth=1, order_index=0,
                     content_hash="h-old", lineage_id="lin-pos")
        new = _node("n", heading="Completely Different", depth=1, order_index=0,
                    content_hash="h-new", version_id="v2")
        matcher = LineageMatcher(confidence_threshold=0.75)
        matches = matcher.match_lineage(_tree(new), _tree(prev))
        assert matches[0].strategy.value == "positional"
        assert matches[0].confidence < 0.75
        assert matches[0].status.value == "needs_review"


class TestStrategyOrdering:
    """Exact match always wins over heading match."""

    def test_exact_takes_priority(self):
        prev = _node("p", heading="Same", content_hash="EXACT", lineage_id="l-prev")
        new = _node("n", heading="Same", content_hash="EXACT", version_id="v2")
        matcher = LineageMatcher(confidence_threshold=0.75)
        matches = matcher.match_lineage(_tree(new), _tree(prev))
        # Even though heading also matches, exact wins
        assert matches[0].strategy.value == "exact"
