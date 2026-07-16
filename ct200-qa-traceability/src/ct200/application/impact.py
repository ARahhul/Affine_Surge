"""Impact analysis use case — orchestrates staleness detection.

Delegates to ImpactAnalyzer which performs read-only comparison
of source hashes against current content hashes.

Staleness is a computed view — never mutates historical generation records (CP-8.1).

Requirements: 8.1-8.6, CP-8.1
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ct200.domain.entities import ImpactReport
from ct200.infrastructure.impact.analyzer import ImpactAnalyzer

logger = structlog.get_logger()


class AnalyzeImpactUseCase:
    """Orchestrates staleness detection for generation records."""

    def __init__(self, session: AsyncSession) -> None:
        self._analyzer = ImpactAnalyzer(session)

    async def execute(self, generation_id: str) -> ImpactReport:
        """Analyze staleness for a generation record.

        Delegates to ImpactAnalyzer which performs read-only comparison
        of source hashes against current content hashes.

        Args:
            generation_id: The generation record ID to analyze.

        Returns:
            ImpactReport with staleness status, changed nodes, and reasons.

        Raises:
            ValueError: If the generation record is not found.
        """
        logger.info("analyze_impact_start", generation_id=generation_id)
        report = await self._analyzer.analyze(generation_id)
        logger.info(
            "analyze_impact_complete",
            generation_id=generation_id,
            is_stale=report.is_stale,
            changed_count=len(report.changed_nodes),
        )
        return report
