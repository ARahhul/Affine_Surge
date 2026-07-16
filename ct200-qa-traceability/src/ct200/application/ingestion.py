"""Ingestion use case — orchestrates PDF upload → parse → tree → version → persist.

Implements the full document ingestion pipeline:
1. Parse PDF via PyMuPDFParser (includes header/footer stripping)
2. Build validated document tree via TreeEngine
3. Check idempotency via content hash
4. Persist version and nodes atomically within a single transaction

Requirements: 2.1, 4.3, 4.6
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ct200.domain.entities import DocumentNode
from ct200.infrastructure.database.models import DocumentModel, NodeModel, VersionModel
from ct200.infrastructure.database.repositories.document import DocumentRepository
from ct200.infrastructure.database.repositories.node import NodeRepository
from ct200.infrastructure.database.repositories.version import VersionRepository
from ct200.infrastructure.parser.pymupdf_parser import PyMuPDFParser
from ct200.infrastructure.parser.reporting import (
    generate_parser_report,
    generate_reconciliation_report,
    generate_validation_report,
)
from ct200.infrastructure.tree.tree_engine import TreeEngine

logger = structlog.get_logger()


class IngestDocumentUseCase:
    """Orchestrates the full document ingestion pipeline.

    Pipeline: validate → parse → build tree → check idempotency → persist.
    All nodes are persisted within a single transaction (CP-4.3).
    Duplicate content is detected via SHA-256 content hash (CP-4.2).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._parser = PyMuPDFParser()
        self._tree_engine = TreeEngine()
        self._doc_repo = DocumentRepository(session)
        self._version_repo = VersionRepository(session)
        self._node_repo = NodeRepository(session)

    async def execute(
        self, pdf_bytes: bytes, filename: str, document_id: str | None = None
    ) -> dict:
        """Execute the full ingestion pipeline.

        Args:
            pdf_bytes: Raw PDF file bytes.
            filename: Original filename.
            document_id: Optional existing document ID (for re-versioning).

        Returns:
            Dict with ingestion result including version_id, is_new, document_id.
        """
        # 1. Compute content hash for idempotency check (before any processing)
        content_hash = hashlib.sha256(pdf_bytes).hexdigest()

        # 2. Parse PDF (includes header/footer stripping internally)
        parsed_content = await self._parser.parse(pdf_bytes, filename)

        # 3. Get or create document
        now = datetime.now(timezone.utc).isoformat()
        if document_id:
            doc = await self._doc_repo.get_by_id(document_id)
            if not doc:
                doc = await self._doc_repo.create(
                    DocumentModel(
                        id=document_id,
                        name=filename,
                        created_at=now,
                        updated_at=now,
                    )
                )
        else:
            document_id = str(uuid.uuid4())
            doc = await self._doc_repo.create(
                DocumentModel(
                    id=document_id,
                    name=filename,
                    created_at=now,
                    updated_at=now,
                )
            )

        # 4. Check idempotency — same content already ingested for this document?
        existing = await self._version_repo.get_by_content_hash(document_id, content_hash)
        if existing:
            logger.info(
                "ingestion_idempotent",
                version_id=existing.id,
                document_id=document_id,
            )
            return {
                "document_id": document_id,
                "version_id": existing.id,
                "version_number": existing.version_number,
                "is_new": False,
                "message": "Content already ingested — returning existing version",
            }

        # 5. Build validated tree
        version_id = str(uuid.uuid4())
        tree = self._tree_engine.build_tree(parsed_content, version_id=version_id)

        # 6. Generate reports
        parser_report = generate_parser_report(parsed_content)
        validation_report = generate_validation_report(stripped_count=0)
        reconciliation = generate_reconciliation_report(
            total_extracted_before_strip=len(parsed_content.blocks),
            content_after_strip=parsed_content,
            stripped_count=0,
        )

        # 7. Determine version number
        latest = await self._version_repo.get_latest(document_id)
        version_number = (latest.version_number + 1) if latest else 1

        # 8. Persist version
        await self._version_repo.create(
            VersionModel(
                id=version_id,
                document_id=document_id,
                version_number=version_number,
                content_hash=content_hash,
                ingested_at=now,
                parser_report_json=json.dumps(parser_report.to_dict()),
                validation_report_json=json.dumps(validation_report.to_dict()),
                block_count=reconciliation.total_extracted,
                mapped_block_count=reconciliation.mapped_blocks,
            )
        )

        # 9. Persist nodes atomically (flatten tree to NodeModel list)
        node_models = self._flatten_tree_to_models(tree.root, version_id)
        await self._node_repo.bulk_create(node_models)

        # 10. Commit the transaction (single atomic write for version + all nodes)
        await self._session.commit()

        logger.info(
            "ingestion_complete",
            document_id=document_id,
            version_id=version_id,
            version_number=version_number,
            node_count=tree.node_count,
        )

        return {
            "document_id": document_id,
            "version_id": version_id,
            "version_number": version_number,
            "is_new": True,
            "node_count": tree.node_count,
            "parser_report": parser_report.to_dict(),
            "reconciliation": reconciliation.to_dict(),
        }

    def _flatten_tree_to_models(
        self, node: DocumentNode, version_id: str
    ) -> list[NodeModel]:
        """Recursively flatten a DocumentTree into a list of NodeModel instances."""
        models: list[NodeModel] = []
        self._collect_nodes(node, models, version_id)
        return models

    def _collect_nodes(
        self, node: DocumentNode, models: list[NodeModel], version_id: str
    ) -> None:
        """Recursively collect NodeModel instances from the tree."""
        model = NodeModel(
            id=node.id,
            version_id=version_id,
            parent_id=node.parent_id,
            heading=node.heading,
            body=node.body,
            depth=node.depth,
            parsed_number=node.parsed_number,
            order_index=node.order_index,
            lineage_id=node.lineage_id,
            content_hash=node.content_hash,
            match_strategy=node.match_strategy.value,
            confidence_score=node.confidence_score,
            lineage_status=node.lineage_status.value,
        )
        models.append(model)
        for child in node.children:
            self._collect_nodes(child, models, version_id)
