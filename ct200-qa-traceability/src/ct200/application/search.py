"""Search nodes use case.

Provides full-text search across document nodes scoped to a specific version.

Requirements: 6.4, 6.5, CP-6.2, CP-6.3
"""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ct200.domain.exceptions import ValidationError
from ct200.infrastructure.database.repositories.node import NodeRepository
from ct200.infrastructure.database.repositories.version import VersionRepository

logger = structlog.get_logger()


class SearchNodesUseCase:
    """Full-text search across nodes in a document version."""

    def __init__(self, session: AsyncSession) -> None:
        self._node_repo = NodeRepository(session)
        self._version_repo = VersionRepository(session)

    async def execute(
        self,
        query: str,
        version_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """Execute full-text search scoped to a version.

        Args:
            query: Search text (minimum 2 characters).
            version_id: Version to scope the search to.
            limit: Max results per page.
            offset: Pagination offset.

        Returns:
            Dict with results list and metadata.

        Raises:
            ValidationError: If query is shorter than 2 characters.
        """
        clean_query = query.strip()
        if len(clean_query) < 2:
            raise ValidationError(
                "Search query must be at least 2 characters",
                details={"query": query},
                code="QUERY_TOO_SHORT",
            )

        results = await self._node_repo.search_fts(
            clean_query, version_id, limit, offset
        )

        logger.info(
            "search_completed",
            query=clean_query,
            version_id=version_id,
            result_count=len(results),
        )

        return {
            "query": clean_query,
            "version_id": version_id,
            "result_count": len(results),
            "results": results,
        }
