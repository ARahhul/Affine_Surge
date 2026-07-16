"""IVersioningEngine protocol — defines the lineage matching contract."""

from __future__ import annotations

from typing import Protocol

from ct200.domain.entities import DocumentTree, LineageMatch


class IVersioningEngine(Protocol):
    """Protocol for the versioning engine that matches nodes across versions.

    Implementors must enforce:
    - CP-5.1: Strategy ordering (exact → heading → positional)
    - CP-5.2: Confidence threshold enforcement (needs_review flagging)
    - CP-5.4: Determinism (same inputs → same outputs)
    """

    def match_lineage(
        self, new_tree: DocumentTree, prev_tree: DocumentTree | None
    ) -> list[LineageMatch]:
        """Match nodes from new_tree against prev_tree.

        Args:
            new_tree: The newly ingested document tree.
            prev_tree: The previous version's tree (None for first version).

        Returns:
            List of LineageMatch results for every node in new_tree.
        """
        ...
