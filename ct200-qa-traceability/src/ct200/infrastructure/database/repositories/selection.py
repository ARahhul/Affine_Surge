"""Selection repository implementation."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ct200.infrastructure.database.models import SelectionModel


class SelectionRepository:
    """Async repository for Selection persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, selection_id: str) -> SelectionModel | None:
        """Retrieve a selection by its ID."""
        result = await self._session.execute(
            select(SelectionModel).where(SelectionModel.id == selection_id)
        )
        return result.scalar_one_or_none()

    async def create(self, selection: SelectionModel) -> SelectionModel:
        """Persist a new selection."""
        self._session.add(selection)
        await self._session.flush()
        return selection

    async def list_by_version(self, version_id: str) -> list[SelectionModel]:
        """List all selections pinned to a specific version."""
        result = await self._session.execute(
            select(SelectionModel).where(
                SelectionModel.version_id == version_id
            )
        )
        return list(result.scalars().all())
