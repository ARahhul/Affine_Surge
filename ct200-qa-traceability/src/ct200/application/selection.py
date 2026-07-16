"""Create selection use case.

Handles creation of immutable, version-pinned selections of document nodes.
Validates all node IDs exist in the specified version before persisting.
Selections are write-once — no mutation after creation (CP-7.1).

Requirements: 7.1, 7.2
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ct200.domain.entities import Selection
from ct200.infrastructure.database.models import NodeModel, SelectionModel
from ct200.infrastructure.database.repositories.node import NodeRepository
from ct200.infrastructure.database.repositories.selection import SelectionRepository


class SelectionError(Exception):
    """Base exception for selection operations."""

    pass


class InvalidNodeIDsError(SelectionError):
    """Raised when one or more node IDs do not belong to the specified version."""

    def __init__(self, invalid_ids: list[str]) -> None:
        self.invalid_ids = invalid_ids
        super().__init__(
            f"Node IDs not found in specified version: {invalid_ids}"
        )


class EmptySelectionError(SelectionError):
    """Raised when no node IDs are provided."""

    def __init__(self) -> None:
        super().__init__("Selection must contain at least one node ID")


class VersionNotFoundError(SelectionError):
    """Raised when the specified version does not exist."""

    def __init__(self, version_id: str) -> None:
        self.version_id = version_id
        super().__init__(f"Version not found: {version_id}")


class CreateSelectionUseCase:
    """Creates immutable, version-pinned selections.

    Validates:
    - At least one node ID is provided
    - All node IDs exist within the specified version
    - The version exists

    Once created, selections cannot be mutated (CP-7.1).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._selection_repo = SelectionRepository(session)
        self._node_repo = NodeRepository(session)

    async def execute(
        self,
        version_id: str,
        node_ids: list[str],
        label: str = "",
    ) -> Selection:
        """Create a new selection pinned to a document version.

        Args:
            version_id: The version to pin this selection to.
            node_ids: List of node IDs to include in the selection.
            label: Optional human-readable label for the selection.

        Returns:
            The created Selection domain entity.

        Raises:
            EmptySelectionError: If node_ids is empty.
            InvalidNodeIDsError: If any node IDs don't exist in the version.
        """
        # Validate non-empty
        if not node_ids:
            raise EmptySelectionError()

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_ids: list[str] = []
        for nid in node_ids:
            if nid not in seen:
                seen.add(nid)
                unique_ids.append(nid)

        # Validate all node IDs exist in the specified version
        version_nodes = await self._node_repo.get_tree(version_id)
        valid_ids = {node.id for node in version_nodes}

        invalid_ids = [nid for nid in unique_ids if nid not in valid_ids]
        if invalid_ids:
            raise InvalidNodeIDsError(invalid_ids)

        # If no valid nodes exist for this version at all, version may not exist
        if not version_nodes and unique_ids:
            raise VersionNotFoundError(version_id)

        # Create the selection model
        selection_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        selection_model = SelectionModel(
            id=selection_id,
            version_id=version_id,
            node_ids_json=json.dumps(unique_ids),
            created_at=now,
            label=label,
        )

        await self._selection_repo.create(selection_model)
        await self._session.commit()

        return Selection(
            id=selection_id,
            version_id=version_id,
            node_ids=unique_ids,
            created_at=now,
            label=label,
        )

    async def get_by_id(self, selection_id: str) -> Selection | None:
        """Retrieve a selection by its ID.

        Returns None if not found.
        """
        model = await self._selection_repo.get_by_id(selection_id)
        if model is None:
            return None

        return Selection(
            id=model.id,
            version_id=model.version_id,
            node_ids=json.loads(model.node_ids_json),
            created_at=model.created_at,
            label=model.label or "",
        )
