"""Version diff use case — computes lightweight diffs between document versions.

Implements Requirements 5.5, 5.6, 5.7 and CP-5.3 (version immutability).

The DiffVersionsUseCase operates purely on persisted data via repositories,
ensuring that previous version records are never mutated (CP-5.3). All
operations are read-only against the node table.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ct200.domain.entities import NodeChange, VersionDiff
from ct200.infrastructure.database.repositories.node import NodeRepository
from ct200.infrastructure.database.repositories.version import VersionRepository

logger = structlog.get_logger()


class DiffVersionsUseCase:
    """Computes the diff between two document versions.

    Identifies added, removed, and modified nodes by comparing
    lineage_ids and content_hashes across versions.

    Guarantees (CP-5.3): This use case ONLY reads from the database.
    No writes are performed to either version's records, ensuring
    previous versions remain immutable.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._version_repo = VersionRepository(session)
        self._node_repo = NodeRepository(session)

    async def execute(self, version_a_id: str, version_b_id: str) -> VersionDiff:
        """Compute diff between version_a and version_b.

        Args:
            version_a_id: The "from" version (typically older).
            version_b_id: The "to" version (typically newer).

        Returns:
            VersionDiff with added, removed, and modified nodes.

        Raises:
            ValueError: If either version ID does not exist.
        """
        # Validate both versions exist
        version_a = await self._version_repo.get_by_id(version_a_id)
        version_b = await self._version_repo.get_by_id(version_b_id)

        if version_a is None:
            raise ValueError(f"Version not found: {version_a_id}")
        if version_b is None:
            raise ValueError(f"Version not found: {version_b_id}")

        # Load nodes for both versions (read-only — CP-5.3)
        nodes_a = await self._node_repo.get_tree(version_a_id)
        nodes_b = await self._node_repo.get_tree(version_b_id)

        # Build lineage maps: lineage_id → (node_id, content_hash)
        a_by_lineage: dict[str, tuple[str, str]] = {}
        for node in nodes_a:
            a_by_lineage[node.lineage_id] = (node.id, node.content_hash)

        b_by_lineage: dict[str, tuple[str, str]] = {}
        for node in nodes_b:
            b_by_lineage[node.lineage_id] = (node.id, node.content_hash)

        # Compute diff
        added: list[str] = []
        removed: list[str] = []
        modified: list[NodeChange] = []

        # Nodes in B but not in A → added
        for lineage_id in b_by_lineage:
            if lineage_id not in a_by_lineage:
                added.append(lineage_id)

        # Nodes in A but not in B → removed
        for lineage_id in a_by_lineage:
            if lineage_id not in b_by_lineage:
                removed.append(lineage_id)

        # Nodes in both but with different hash → modified
        for lineage_id in a_by_lineage:
            if lineage_id in b_by_lineage:
                _, hash_a = a_by_lineage[lineage_id]
                _, hash_b = b_by_lineage[lineage_id]
                if hash_a != hash_b:
                    modified.append(
                        NodeChange(
                            lineage_id=lineage_id,
                            change_type="direct",
                            old_hash=hash_a,
                            new_hash=hash_b,
                            diff_summary=f"Content changed (hash {hash_a[:8]}→{hash_b[:8]})",
                        )
                    )

        logger.info(
            "version_diff_computed",
            version_a=version_a_id,
            version_b=version_b_id,
            added=len(added),
            removed=len(removed),
            modified=len(modified),
        )

        return VersionDiff(
            version_a_id=version_a_id,
            version_b_id=version_b_id,
            added_nodes=added,
            removed_nodes=removed,
            modified_nodes=modified,
        )
