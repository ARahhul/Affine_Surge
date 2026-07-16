"""Document repository implementation."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ct200.infrastructure.database.models import DocumentModel


class DocumentRepository:
    """Async repository for Document persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, doc_id: str) -> DocumentModel | None:
        """Retrieve a document by its ID."""
        result = await self._session.execute(
            select(DocumentModel).where(DocumentModel.id == doc_id)
        )
        return result.scalar_one_or_none()

    async def create(self, document: DocumentModel) -> DocumentModel:
        """Persist a new document."""
        self._session.add(document)
        await self._session.flush()
        return document

    async def list_all(self) -> list[DocumentModel]:
        """List all tracked documents."""
        result = await self._session.execute(select(DocumentModel))
        return list(result.scalars().all())
