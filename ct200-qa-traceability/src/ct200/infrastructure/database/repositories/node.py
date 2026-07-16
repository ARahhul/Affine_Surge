"""Node repository implementation."""

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ct200.infrastructure.database.models import NodeModel


class NodeRepository:
    """Async repository for Node persistence.

    Supports atomic bulk creation (CP-4.3) and FTS5 search.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, node_id: str) -> NodeModel | None:
        """Retrieve a node by its ID."""
        result = await self._session.execute(
            select(NodeModel).where(NodeModel.id == node_id)
        )
        return result.scalar_one_or_none()

    async def get_tree(self, version_id: str) -> list[NodeModel]:
        """Retrieve all nodes belonging to a version, ordered for tree reconstruction.

        Returns nodes ordered by depth then order_index so callers can
        reconstruct the tree hierarchy.
        """
        result = await self._session.execute(
            select(NodeModel)
            .where(NodeModel.version_id == version_id)
            .order_by(NodeModel.depth, NodeModel.order_index)
        )
        return list(result.scalars().all())

    async def bulk_create(self, nodes: list[NodeModel]) -> None:
        """Persist all nodes in a single transaction (CP-4.3).

        All nodes are added to the session and flushed together.
        If any constraint violation or error occurs, the entire batch
        is rolled back by the caller's transaction management — no
        partial commits are possible.
        """
        self._session.add_all(nodes)
        await self._session.flush()

    async def search_fts(
        self, query: str, version_id: str, limit: int = 20, offset: int = 0
    ) -> list[NodeModel]:
        """Full-text search across nodes in a specific version using FTS5.

        Falls back to LIKE-based search if the FTS5 virtual table
        does not exist (e.g., in test environments without migrations).
        """
        # Try FTS5 search first
        try:
            fts_sql = text(
                "SELECT node_id FROM nodes_fts "
                "WHERE nodes_fts MATCH :query"
            )
            fts_result = await self._session.execute(
                fts_sql, {"query": query}
            )
            node_ids = [row[0] for row in fts_result.fetchall()]

            if not node_ids:
                return []

            # Filter by version and apply pagination
            result = await self._session.execute(
                select(NodeModel)
                .where(
                    NodeModel.id.in_(node_ids),
                    NodeModel.version_id == version_id,
                )
                .order_by(NodeModel.depth, NodeModel.order_index)
                .limit(limit)
                .offset(offset)
            )
            return list(result.scalars().all())
        except Exception:
            # Fallback: LIKE-based search when FTS5 table is unavailable
            like_pattern = f"%{query}%"
            result = await self._session.execute(
                select(NodeModel)
                .where(
                    NodeModel.version_id == version_id,
                    (NodeModel.heading.like(like_pattern))
                    | (NodeModel.body.like(like_pattern)),
                )
                .order_by(NodeModel.depth, NodeModel.order_index)
                .limit(limit)
                .offset(offset)
            )
            return list(result.scalars().all())
