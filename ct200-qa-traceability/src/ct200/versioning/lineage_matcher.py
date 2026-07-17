"""Three-tier lineage matching engine.

Matches nodes between document versions using:
1. Exact content hash match (confidence = 1.0)
2. Parent-lineage + heading match (confidence 0.7-0.95)
3. Positional fallback (confidence 0.5-0.7)

Low-confidence matches (below threshold) get needs_review status (CP-5.2).
Strategy order is strictly enforced (CP-5.1): hash → heading → positional.
"""

from __future__ import annotations

import structlog

from ct200.models import (
    DocumentNode,
    DocumentTree,
    LineageMatch,
    LineageStatus,
    MatchStrategy,
)

logger = structlog.get_logger()


class LineageMatcher:
    """Matches nodes across document versions using a three-tier strategy.

    Implements the IVersioningEngine.match_lineage protocol.

    Tier order (CP-5.1):
        1. Exact Content_Hash match → confidence = 1.0
        2. Parent-lineage + heading match → confidence 0.7-0.95
        3. Positional fallback → confidence 0.5-0.7

    Any match below the configured threshold is flagged needs_review (CP-5.2).
    """

    def __init__(self, confidence_threshold: float | None = None) -> None:
        if confidence_threshold is not None:
            self._threshold = confidence_threshold
        else:
            self._threshold = 0.75  # Default threshold

    def match_lineage(
        self, new_tree: DocumentTree, prev_tree: DocumentTree | None
    ) -> list[LineageMatch]:
        """Match nodes from new_tree against prev_tree using three-tier strategy.

        Args:
            new_tree: The newly ingested document tree.
            prev_tree: The previous version's tree (None for first version).

        Returns:
            List of LineageMatch results for every node in new_tree.
        """
        if prev_tree is None:
            # First version — all nodes are NEW
            return self._mark_all_new(new_tree)

        # Flatten both trees for matching
        new_nodes = self._flatten(new_tree.root)
        prev_nodes = self._flatten(prev_tree.root)

        # Build lookup maps for prev tree
        prev_by_hash: dict[str, list[DocumentNode]] = {}
        prev_by_heading: dict[str, list[DocumentNode]] = {}
        prev_by_position: list[DocumentNode] = prev_nodes

        for node in prev_nodes:
            if node.content_hash not in prev_by_hash:
                prev_by_hash[node.content_hash] = []
            prev_by_hash[node.content_hash].append(node)

            heading_key = node.heading.strip().lower()
            if heading_key not in prev_by_heading:
                prev_by_heading[heading_key] = []
            prev_by_heading[heading_key].append(node)

        matches: list[LineageMatch] = []
        matched_prev_ids: set[str] = set()

        for new_node in new_nodes:
            match = self._match_node(
                new_node,
                prev_by_hash,
                prev_by_heading,
                prev_by_position,
                matched_prev_ids,
            )
            matches.append(match)
            if match.strategy != MatchStrategy.NEW:
                matched_prev_ids.add(match.lineage_id)

        logger.info(
            "lineage_matching_complete",
            total_nodes=len(new_nodes),
            exact_matches=sum(1 for m in matches if m.strategy == MatchStrategy.EXACT),
            heading_matches=sum(1 for m in matches if m.strategy == MatchStrategy.HEADING),
            positional_matches=sum(1 for m in matches if m.strategy == MatchStrategy.POSITIONAL),
            new_nodes=sum(1 for m in matches if m.strategy == MatchStrategy.NEW),
            needs_review=sum(1 for m in matches if m.status == LineageStatus.NEEDS_REVIEW),
        )

        return matches

    def _match_node(
        self,
        new_node: DocumentNode,
        prev_by_hash: dict[str, list[DocumentNode]],
        prev_by_heading: dict[str, list[DocumentNode]],
        prev_by_position: list[DocumentNode],
        matched_prev_ids: set[str],
    ) -> LineageMatch:
        """Match a single node using the three-tier strategy (CP-5.1: strict order)."""

        # TIER 1: Exact content hash match (confidence = 1.0)
        if new_node.content_hash in prev_by_hash:
            candidates = [
                n
                for n in prev_by_hash[new_node.content_hash]
                if n.lineage_id not in matched_prev_ids
            ]
            if candidates:
                prev_node = candidates[0]
                return LineageMatch(
                    node_id=new_node.id,
                    lineage_id=prev_node.lineage_id,
                    strategy=MatchStrategy.EXACT,
                    confidence=1.0,
                    status=LineageStatus.MATCHED,
                )

        # TIER 2: Parent-lineage + heading match
        heading_key = new_node.heading.strip().lower()
        if heading_key and heading_key in prev_by_heading:
            candidates = [
                n for n in prev_by_heading[heading_key] if n.lineage_id not in matched_prev_ids
            ]
            if candidates:
                # Score by depth similarity and parent position
                best = self._best_heading_candidate(new_node, candidates)
                confidence = self._compute_heading_confidence(new_node, best)
                status = self._determine_status(confidence)
                return LineageMatch(
                    node_id=new_node.id,
                    lineage_id=best.lineage_id,
                    strategy=MatchStrategy.HEADING,
                    confidence=confidence,
                    status=status,
                )

        # TIER 3: Positional fallback
        unmatched_prev = [
            n
            for n in prev_by_position
            if n.lineage_id not in matched_prev_ids and n.depth == new_node.depth
        ]
        if unmatched_prev:
            # Match to closest positional candidate at same depth
            best = self._best_positional_candidate(new_node, unmatched_prev)
            confidence = self._compute_positional_confidence(new_node, best)
            status = self._determine_status(confidence)
            return LineageMatch(
                node_id=new_node.id,
                lineage_id=best.lineage_id,
                strategy=MatchStrategy.POSITIONAL,
                confidence=confidence,
                status=status,
            )

        # No match found — this is a new node
        return LineageMatch(
            node_id=new_node.id,
            lineage_id=new_node.lineage_id,  # Keep its own lineage_id
            strategy=MatchStrategy.NEW,
            confidence=1.0,
            status=LineageStatus.NEW,
        )

    def _best_heading_candidate(
        self, new_node: DocumentNode, candidates: list[DocumentNode]
    ) -> DocumentNode:
        """Select the best heading candidate by depth and position similarity."""

        def score(candidate: DocumentNode) -> float:
            s = 0.0
            if candidate.depth == new_node.depth:
                s += 2.0
            if abs(candidate.order_index - new_node.order_index) <= 1:
                s += 1.0
            return s

        return max(candidates, key=score)

    def _best_positional_candidate(
        self, new_node: DocumentNode, candidates: list[DocumentNode]
    ) -> DocumentNode:
        """Select the best positional candidate by order_index proximity."""

        def distance(candidate: DocumentNode) -> int:
            return abs(candidate.order_index - new_node.order_index)

        return min(candidates, key=distance)

    def _compute_heading_confidence(self, new_node: DocumentNode, prev_node: DocumentNode) -> float:
        """Compute confidence for heading-based match (range 0.7-0.95)."""
        confidence = 0.8  # Base confidence for heading match

        # Boost if depth matches
        if new_node.depth == prev_node.depth:
            confidence += 0.1

        # Boost if order_index is close
        if abs(new_node.order_index - prev_node.order_index) <= 1:
            confidence += 0.05

        return min(confidence, 0.95)

    def _compute_positional_confidence(
        self, new_node: DocumentNode, prev_node: DocumentNode
    ) -> float:
        """Compute confidence for positional fallback match (range 0.5-0.7)."""
        confidence = 0.5  # Base confidence for positional match

        # Boost if order indices are identical
        if new_node.order_index == prev_node.order_index:
            confidence += 0.15

        # Boost slightly if headings share some similarity
        if new_node.heading and prev_node.heading:
            # Simple Jaccard similarity on words
            new_words = set(new_node.heading.lower().split())
            prev_words = set(prev_node.heading.lower().split())
            union = new_words | prev_words
            if union:
                overlap = len(new_words & prev_words) / len(union)
                confidence += overlap * 0.2

        return min(confidence, 0.7)

    def _determine_status(self, confidence: float) -> LineageStatus:
        """Determine lineage status based on confidence threshold (CP-5.2).

        Any match below the configured threshold is flagged needs_review.
        """
        if confidence < self._threshold:
            return LineageStatus.NEEDS_REVIEW
        return LineageStatus.MATCHED

    def _mark_all_new(self, tree: DocumentTree) -> list[LineageMatch]:
        """Mark all nodes in a tree as NEW (first version)."""
        nodes = self._flatten(tree.root)
        return [
            LineageMatch(
                node_id=node.id,
                lineage_id=node.lineage_id,
                strategy=MatchStrategy.NEW,
                confidence=1.0,
                status=LineageStatus.NEW,
            )
            for node in nodes
        ]

    def _flatten(self, node: DocumentNode) -> list[DocumentNode]:
        """Flatten a tree into a list (pre-order traversal)."""
        result: list[DocumentNode] = [node]
        for child in node.children:
            result.extend(self._flatten(child))
        return result
