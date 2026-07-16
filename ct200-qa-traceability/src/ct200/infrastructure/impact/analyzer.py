"""Impact analyzer — detects stale generations by comparing source hashes.

Compares stored generation source-hashes against the latest lineage hashes.
Returns stale status, changed nodes, diff summary, and human-readable reasons.
Distinguishes direct node changes from descendant changes.
Staleness is a computed view — never mutates historical records (CP-8.1).

Requirements: 8.1-8.6, CP-8.1, CP-8.2, CP-8.3
"""

from __future__ import annotations

import json

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ct200.domain.entities import ImpactReport, NodeChange
from ct200.infrastructure.database.repositories.generation import GenerationRepository
from ct200.infrastructure.database.repositories.node import NodeRepository
from ct200.infrastructure.database.repositories.selection import SelectionRepository
from ct200.infrastructure.database.repositories.version import VersionRepository

logger = structlog.get_logger()


class ImpactAnalyzer:
    """Analyzes staleness for generation records.

    Compares source_hashes stored at generation time against the
    current content_hashes in the latest document version.

    All operations are READ-ONLY — generation records are never mutated (CP-8.1).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._gen_repo = GenerationRepository(session)
        self._node_repo = NodeRepository(session)
        self._selection_repo = SelectionRepository(session)
        self._version_repo = VersionRepository(session)

    async def analyze(self, generation_id: str) -> ImpactReport:
        """Analyze staleness for a specific generation.

        Args:
            generation_id: The generation record to analyze.

        Returns:
            ImpactReport with is_stale, changed_nodes, changes, reasons.

        Raises:
            ValueError: If generation_id doesn't exist.
        """
        # 1. Load generation record (READ-ONLY — never modify)
        gen = await self._gen_repo.get_by_id(generation_id)
        if gen is None:
            raise ValueError(f"Generation not found: {generation_id}")

        source_hashes: dict[str, str] = json.loads(gen.source_hashes_json)

        # 2. Get the selection to find the document
        selection = await self._selection_repo.get_by_id(gen.selection_id)
        if selection is None:
            raise ValueError(f"Selection not found: {gen.selection_id}")

        # 3. Get the version to find the document_id
        version = await self._version_repo.get_by_id(selection.version_id)
        if version is None:
            raise ValueError(f"Version not found: {selection.version_id}")

        # 4. Get the latest version of the document
        latest_version = await self._version_repo.get_latest(version.document_id)
        if latest_version is None:
            raise ValueError(f"No versions found for document: {version.document_id}")

        # 5. Load nodes from the latest version
        latest_nodes = await self._node_repo.get_tree(latest_version.id)

        # Build lineage_id → node map for the latest version
        latest_by_lineage: dict[str, object] = {}
        for node in latest_nodes:
            latest_by_lineage[node.lineage_id] = node

        # Also load original version nodes to get lineage mapping
        original_nodes = await self._node_repo.get_tree(selection.version_id)
        original_by_id: dict[str, object] = {}
        for node in original_nodes:
            original_by_id[node.id] = node

        # 6. Compare source hashes against latest
        changed_nodes: list[str] = []
        changes: list[NodeChange] = []
        reasons: list[str] = []

        for node_id, source_hash in source_hashes.items():
            # Find the original node to get its lineage_id
            orig_node = original_by_id.get(node_id)
            if orig_node is None:
                continue

            lineage_id = orig_node.lineage_id

            # Find matching node in latest version by lineage_id
            latest_node = latest_by_lineage.get(lineage_id)

            if latest_node is None:
                # Node removed or unmatched in latest version (Req 8.4)
                changed_nodes.append(lineage_id)
                changes.append(NodeChange(
                    lineage_id=lineage_id,
                    change_type="removed",
                    old_hash=source_hash,
                    new_hash="",
                    diff_summary=f"Node '{orig_node.heading}' not found in latest version",
                ))
                reasons.append(
                    f"Node '{orig_node.heading}' (lineage={lineage_id[:8]}) "
                    f"was removed or unmatched in latest version"
                )
            elif latest_node.content_hash != source_hash:
                # Content changed — classify as direct or descendant (Req 8.5)
                change_type = self._classify_change(
                    orig_node, latest_node, latest_nodes
                )
                changed_nodes.append(lineage_id)
                changes.append(NodeChange(
                    lineage_id=lineage_id,
                    change_type=change_type,
                    old_hash=source_hash,
                    new_hash=latest_node.content_hash,
                    diff_summary=f"Node '{orig_node.heading}' content changed ({change_type})",
                ))
                reasons.append(
                    f"Node '{orig_node.heading}' (lineage={lineage_id[:8]}) "
                    f"has a {change_type} content change"
                )

        is_stale = len(changed_nodes) > 0

        logger.info(
            "impact_analysis_complete",
            generation_id=generation_id,
            is_stale=is_stale,
            changed_count=len(changed_nodes),
        )

        return ImpactReport(
            generation_id=generation_id,
            is_stale=is_stale,
            changed_nodes=changed_nodes,
            changes=changes,
            reasons=reasons,
        )

    def _classify_change(
        self,
        orig_node: object,
        latest_node: object,
        latest_nodes: list[object],
    ) -> str:
        """Classify whether a change is direct or descendant.

        Direct: the node's own heading/body changed.
        Descendant: only child nodes changed (hash differs due to
        structural change below this node).
        """
        # If heading or body differ between the two nodes directly,
        # it's a direct change
        if (orig_node.heading != latest_node.heading
                or orig_node.body != latest_node.body):
            return "direct"

        # Otherwise it's a descendant change (content_hash changed
        # but heading+body are the same — implies child structure changed)
        return "descendant"
