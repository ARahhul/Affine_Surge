"""Parser reporting and content reconciliation.

Generates parser_report and validation_report data structures containing
extraction statistics and structural validation results. Implements
content reconciliation to ensure zero blocks vanish unexplained (CP-2.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ct200.models import BlockType, ParsedContent


@dataclass
class ParserReport:
    """Extraction statistics from PDF parsing."""

    total_pages: int = 0
    headings_extracted: int = 0
    tables_extracted: int = 0
    list_items_extracted: int = 0
    body_blocks_extracted: int = 0
    total_blocks_extracted: int = 0

    def to_dict(self) -> dict[str, int]:
        """Serialize to dictionary for JSON output."""
        return {
            "total_pages": self.total_pages,
            "headings_extracted": self.headings_extracted,
            "tables_extracted": self.tables_extracted,
            "list_items_extracted": self.list_items_extracted,
            "body_blocks_extracted": self.body_blocks_extracted,
            "total_blocks_extracted": self.total_blocks_extracted,
        }


@dataclass
class ValidationReport:
    """Structural validation results."""

    ordering_violations: int = 0
    repeated_headers_stripped: int = 0
    multi_column_pages: int = 0

    def to_dict(self) -> dict[str, int]:
        """Serialize to dictionary for JSON output."""
        return {
            "ordering_violations": self.ordering_violations,
            "repeated_headers_stripped": self.repeated_headers_stripped,
            "multi_column_pages": self.multi_column_pages,
        }


@dataclass
class ReconciliationReport:
    """Content reconciliation — accounts for 100% of extracted blocks.

    Invariant: total_extracted == mapped_blocks + unmapped_blocks
    Zero blocks may vanish unexplained.
    """

    total_extracted: int = 0
    mapped_blocks: int = 0
    unmapped_blocks: int = 0
    unmapped_reasons: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Serialize to dictionary for JSON output."""
        return {
            "total_extracted": self.total_extracted,
            "mapped_blocks": self.mapped_blocks,
            "unmapped_blocks": self.unmapped_blocks,
            "reconciliation_valid": self.total_extracted == self.mapped_blocks + self.unmapped_blocks,
            "unmapped_reasons": self.unmapped_reasons,
        }


def generate_parser_report(content: ParsedContent) -> ParserReport:
    """Generate extraction statistics from parsed content.

    Counts blocks by type across all pages.

    Args:
        content: The parsed document content.

    Returns:
        ParserReport with counts per block type.
    """
    report = ParserReport(total_pages=content.total_pages)

    for block in content.blocks:
        match block.block_type:
            case BlockType.HEADING:
                report.headings_extracted += 1
            case BlockType.TABLE:
                report.tables_extracted += 1
            case BlockType.LIST_ITEM:
                report.list_items_extracted += 1
            case BlockType.BODY:
                report.body_blocks_extracted += 1

    report.total_blocks_extracted = len(content.blocks)
    return report


def generate_validation_report(
    stripped_count: int = 0,
    multi_column_pages: int = 0,
    ordering_violations: int = 0,
) -> ValidationReport:
    """Generate structural validation results.

    Args:
        stripped_count: Number of repeated header/footer elements removed.
        multi_column_pages: Number of pages with multi-column layout detected.
        ordering_violations: Number of ordering inconsistencies detected.

    Returns:
        ValidationReport with structural validation counts.
    """
    return ValidationReport(
        ordering_violations=ordering_violations,
        repeated_headers_stripped=stripped_count,
        multi_column_pages=multi_column_pages,
    )


def generate_reconciliation_report(
    total_extracted_before_strip: int,
    content_after_strip: ParsedContent,
    stripped_count: int = 0,
) -> ReconciliationReport:
    """Generate content reconciliation report.

    Accounts for 100% of extracted blocks:
    - mapped_blocks: blocks present in final output
    - unmapped_blocks: blocks removed (with reasons)

    Invariant: total_extracted == mapped_blocks + unmapped_blocks (CP-2.2)

    Args:
        total_extracted_before_strip: Block count before header/footer stripping.
        content_after_strip: ParsedContent after stripping.
        stripped_count: Number of blocks removed by stripping.

    Returns:
        ReconciliationReport with full accounting.
    """
    mapped = len(content_after_strip.blocks)
    unmapped = stripped_count

    unmapped_reasons: list[dict[str, str]] = []
    if stripped_count > 0:
        unmapped_reasons.append(
            {
                "reason": "repeated_header_footer",
                "count": str(stripped_count),
                "description": "Removed as repeated running headers/footers across consecutive pages",
            }
        )

    return ReconciliationReport(
        total_extracted=total_extracted_before_strip,
        mapped_blocks=mapped,
        unmapped_blocks=unmapped,
        unmapped_reasons=unmapped_reasons,
    )
