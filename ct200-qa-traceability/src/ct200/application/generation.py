"""Generate test cases use case.

Orchestrates: selection → prompt → NIM → validate → persist.
- Requests strict JSON output from NIM
- Validates against Pydantic schema, retries once on schema failure
- On success: GenerationRecord(status=completed) with test cases, source_hashes, tokens
- On double failure: GenerationRecord(status=generation_failed) with error details (CP-7.2)
- On timeout/network failure: terminal generation_failed record
- Records input/output token counts per call

Requirements: 7.3-7.10
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ct200.domain.entities import GenerationRecord, GenerationStatus
from ct200.infrastructure.database.models import GenerationModel
from ct200.infrastructure.database.repositories.generation import GenerationRepository
from ct200.infrastructure.database.repositories.node import NodeRepository
from ct200.infrastructure.database.repositories.selection import SelectionRepository
from ct200.infrastructure.generation.nim_client import (
    NIMClient,
    NIMClientError,
    NIMSchemaError,
    NIMTimeoutError,
    NIMTransientError,
)
from ct200.infrastructure.generation.prompt_templates import build_prompt

logger = logging.getLogger(__name__)


class GenerationError(Exception):
    """Base exception for generation operations."""

    pass


class SelectionNotFoundError(GenerationError):
    """Raised when the selection does not exist."""

    def __init__(self, selection_id: str) -> None:
        self.selection_id = selection_id
        super().__init__(f"Selection not found: {selection_id}")


class GenerateTestCasesUseCase:
    """Orchestrates QA test case generation from a selection.

    Pipeline: selection → fetch nodes → build prompt → NIM → validate → persist
    """

    def __init__(
        self,
        session: AsyncSession,
        nim_client: NIMClient,
    ) -> None:
        self._session = session
        self._nim_client = nim_client
        self._selection_repo = SelectionRepository(session)
        self._generation_repo = GenerationRepository(session)
        self._node_repo = NodeRepository(session)

    async def execute(self, selection_id: str) -> GenerationRecord:
        """Generate test cases for a selection.

        Args:
            selection_id: The selection to generate test cases for.

        Returns:
            A GenerationRecord with status=completed or status=generation_failed.

        Raises:
            SelectionNotFoundError: If the selection doesn't exist.
        """
        # 1. Fetch selection
        selection_model = await self._selection_repo.get_by_id(selection_id)
        if selection_model is None:
            raise SelectionNotFoundError(selection_id)

        node_ids = json.loads(selection_model.node_ids_json)

        # 2. Fetch nodes and build source hashes
        source_hashes: dict[str, str] = {}
        node_contents: list[dict[str, str]] = []

        for node_id in node_ids:
            node = await self._node_repo.get_by_id(node_id)
            if node is not None:
                source_hashes[node.id] = node.content_hash
                node_contents.append({
                    "heading": node.heading or "Untitled",
                    "body": node.body or "",
                })

        # 3. Build prompt
        messages = build_prompt(node_contents)

        # 4. Create initial pending generation record
        generation_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        gen_model = GenerationModel(
            id=generation_id,
            selection_id=selection_id,
            status=GenerationStatus.PENDING.value,
            source_hashes_json=json.dumps(source_hashes),
            output_json=None,
            input_tokens=0,
            output_tokens=0,
            model_id=self._nim_client.model_id,
            retry_count=0,
            error_message=None,
            created_at=now,
            completed_at=None,
        )
        await self._generation_repo.create(gen_model)
        await self._session.commit()

        # 5. Call NIM API
        try:
            nim_response = await self._nim_client.generate(messages)

            # Success — update record
            gen_model.status = GenerationStatus.COMPLETED.value
            gen_model.output_json = nim_response.raw_json
            gen_model.input_tokens = nim_response.input_tokens
            gen_model.output_tokens = nim_response.output_tokens
            gen_model.completed_at = datetime.now(timezone.utc).isoformat()
            await self._session.commit()

            return GenerationRecord(
                id=generation_id,
                selection_id=selection_id,
                status=GenerationStatus.COMPLETED,
                source_hashes=source_hashes,
                output_json=nim_response.raw_json,
                input_tokens=nim_response.input_tokens,
                output_tokens=nim_response.output_tokens,
                model_id=self._nim_client.model_id,
                retry_count=0,
                created_at=now,
                completed_at=gen_model.completed_at,
            )

        except NIMSchemaError as exc:
            # Double schema failure (CP-7.2)
            logger.error(f"Generation schema failure: {exc}")
            return await self._mark_failed(
                gen_model, f"Schema validation failed after retry: {exc}", retry_count=1
            )

        except NIMTimeoutError as exc:
            # Hard timeout — terminal failure
            logger.error(f"Generation timeout: {exc}")
            return await self._mark_failed(
                gen_model, f"Timeout: {exc}", retry_count=0
            )

        except (NIMTransientError, NIMClientError) as exc:
            # Network/transient failure — terminal
            logger.error(f"Generation network failure: {exc}")
            return await self._mark_failed(
                gen_model, f"Network error: {exc}", retry_count=0
            )

        except Exception as exc:
            # Unexpected error — still record it
            logger.exception(f"Unexpected generation error: {exc}")
            return await self._mark_failed(
                gen_model, f"Unexpected error: {exc}", retry_count=0
            )

    async def _mark_failed(
        self,
        gen_model: GenerationModel,
        error_message: str,
        retry_count: int,
    ) -> GenerationRecord:
        """Mark a generation record as failed and persist."""
        gen_model.status = GenerationStatus.FAILED.value
        gen_model.error_message = error_message
        gen_model.retry_count = retry_count
        gen_model.completed_at = datetime.now(timezone.utc).isoformat()
        await self._session.commit()

        return GenerationRecord(
            id=gen_model.id,
            selection_id=gen_model.selection_id,
            status=GenerationStatus.FAILED,
            source_hashes=json.loads(gen_model.source_hashes_json),
            output_json=None,
            input_tokens=gen_model.input_tokens,
            output_tokens=gen_model.output_tokens,
            model_id=gen_model.model_id,
            retry_count=retry_count,
            error_message=error_message,
            created_at=gen_model.created_at,
            completed_at=gen_model.completed_at,
        )

    async def get_by_id(self, generation_id: str) -> GenerationRecord | None:
        """Retrieve a generation record by its ID."""
        model = await self._generation_repo.get_by_id(generation_id)
        if model is None:
            return None

        return GenerationRecord(
            id=model.id,
            selection_id=model.selection_id,
            status=GenerationStatus(model.status),
            source_hashes=json.loads(model.source_hashes_json),
            output_json=model.output_json,
            input_tokens=model.input_tokens,
            output_tokens=model.output_tokens,
            model_id=model.model_id,
            retry_count=model.retry_count,
            error_message=model.error_message,
            created_at=model.created_at,
            completed_at=model.completed_at,
        )
