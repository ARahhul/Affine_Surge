"""Generation repository implementation."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ct200.infrastructure.database.models import (
    GenerationModel,
    SelectionModel,
    VersionModel,
)


class GenerationRepository:
    """Async repository for Generation record persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, gen_id: str) -> GenerationModel | None:
        """Retrieve a generation record by its ID."""
        result = await self._session.execute(
            select(GenerationModel).where(GenerationModel.id == gen_id)
        )
        return result.scalar_one_or_none()

    async def create(self, record: GenerationModel) -> GenerationModel:
        """Persist a new generation record."""
        self._session.add(record)
        await self._session.flush()
        return record

    async def list_by_selection(
        self, selection_id: str
    ) -> list[GenerationModel]:
        """List all generation records for a given selection."""
        result = await self._session.execute(
            select(GenerationModel).where(
                GenerationModel.selection_id == selection_id
            )
        )
        return list(result.scalars().all())

    async def list_by_document(self, doc_id: str) -> list[GenerationModel]:
        """List all generation records for a given document.

        Joins through selections → versions to find all generations
        belonging to a document.
        """
        result = await self._session.execute(
            select(GenerationModel)
            .join(
                SelectionModel,
                GenerationModel.selection_id == SelectionModel.id,
            )
            .join(
                VersionModel,
                SelectionModel.version_id == VersionModel.id,
            )
            .where(VersionModel.document_id == doc_id)
        )
        return list(result.scalars().all())
