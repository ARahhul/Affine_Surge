"""Version repository implementation."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ct200.infrastructure.database.models import VersionModel


class VersionRepository:
    """Async repository for Version persistence.

    Supports content-hash based idempotent version check (CP-4.2).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, version_id: str) -> VersionModel | None:
        """Retrieve a version by its ID."""
        result = await self._session.execute(
            select(VersionModel).where(VersionModel.id == version_id)
        )
        return result.scalar_one_or_none()

    async def get_by_content_hash(
        self, doc_id: str, content_hash: str
    ) -> VersionModel | None:
        """Check if a version with the same content hash already exists.

        This enables idempotent ingestion: if the same document content
        is uploaded again, we return the existing version instead of
        creating a duplicate (CP-4.2).
        """
        result = await self._session.execute(
            select(VersionModel).where(
                VersionModel.document_id == doc_id,
                VersionModel.content_hash == content_hash,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, version: VersionModel) -> VersionModel:
        """Persist a new version."""
        self._session.add(version)
        await self._session.flush()
        return version

    async def get_latest(self, doc_id: str) -> VersionModel | None:
        """Retrieve the latest version for a given document (highest version_number)."""
        result = await self._session.execute(
            select(VersionModel)
            .where(VersionModel.document_id == doc_id)
            .order_by(VersionModel.version_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
