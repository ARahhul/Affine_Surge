"""Browse tree use case with change detection support.

Provides tree browsing and version-to-version change detection.

Requirements: 6.1, 6.8, CP-6.3
"""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ct200.infrastructure.database.repositories.node import NodeRepository
from ct200.infrastructure.database.repositories.version import VersionRepository

logger = structlog.get_logger()


class BrowseTreeUseCase:
    """Browse document tree with change detection between versions."""

    def __init__(self, session: AsyncSession) -> None:
        self._node_repo = NodeRepository(session)
        self._version_repo = VersionRepository(session)

    async def get_changes_since(
        self, version_id: str, prev_version_id: str
    ) -> list[dict]:
        """Detect changes between two versions.

        Compares nodes by lineage_id and content_hash to identify
        additions, modifications, and removals.

        Returns list of changed nodes with:
        - lineage_id: stable cross-version identifier
        - node_id: current node ID (or previous for removals)
        - heading: node heading text
        - previous_hash: content_hash in previous version (None if added)
        - current_hash: content_hash in current version (None if removed)
        - change_type: "added", "modified", or "removed"
        """
        current_nodes = await self._node_repo.get_tree(version_id)
        prev_nodes = await self._node_repo.get_tree(prev_version_id)

        # Build lineage maps for O(1) lookup
        current_by_lineage = {n.lineage_id: n for n in current_nodes}
        prev_by_lineage = {n.lineage_id: n for n in prev_nodes}

        changes: list[dict] = []

        # Added: present in current but not in previous
        for lineage_id, node in current_by_lineage.items():
            if lineage_id not in prev_by_lineage:
                changes.append({
                    "lineage_id": lineage_id,
                    "node_id": node.id,
                    "heading": node.heading,
                    "previous_hash": None,
                    "current_hash": node.content_hash,
                    "change_type": "added",
                })

        # Removed: present in previous but not in current
        for lineage_id, node in prev_by_lineage.items():
            if lineage_id not in current_by_lineage:
                changes.append({
                    "lineage_id": lineage_id,
                    "node_id": node.id,
                    "heading": node.heading,
                    "previous_hash": node.content_hash,
                    "current_hash": None,
                    "change_type": "removed",
                })

        # Modified: same lineage_id, different content_hash
        for lineage_id, curr_node in current_by_lineage.items():
            if lineage_id in prev_by_lineage:
                prev_node = prev_by_lineage[lineage_id]
                if curr_node.content_hash != prev_node.content_hash:
                    changes.append({
                        "lineage_id": lineage_id,
                        "node_id": curr_node.id,
                        "heading": curr_node.heading,
                        "previous_hash": prev_node.content_hash,
                        "current_hash": curr_node.content_hash,
                        "change_type": "modified",
                    })

        logger.info(
            "change_detection_complete",
            version_id=version_id,
            prev_version_id=prev_version_id,
            total_changes=len(changes),
        )

        return changes
