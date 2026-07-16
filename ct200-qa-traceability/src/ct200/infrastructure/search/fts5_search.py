"""FTS5 full-text search implementation.

Provides helper utilities for FTS5 indexing and maintenance.
The actual search logic lives in NodeRepository.search_fts() which
directly queries the nodes_fts virtual table.

This module handles FTS5 table creation and index synchronization.

Requirements: 6.4, 6.5, CP-6.2
"""

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


async def ensure_fts5_table(session: AsyncSession) -> None:
    """Create the FTS5 virtual table if it doesn't exist.

    The nodes_fts table indexes heading and body columns for full-text search.
    Uses the porter tokenizer for English stemming support.
    """
    create_sql = text(
        "CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5("
        "node_id UNINDEXED, heading, body, "
        "tokenize='porter unicode61'"
        ")"
    )
    await session.execute(create_sql)
    await session.commit()
    logger.info("fts5_table_ensured")


async def sync_fts5_index(session: AsyncSession, version_id: str) -> int:
    """Synchronize the FTS5 index for all nodes in a given version.

    Inserts or replaces FTS5 entries for all nodes belonging to the
    specified version. Returns the number of indexed nodes.
    """
    # Clear existing entries for this version's nodes
    delete_sql = text(
        "DELETE FROM nodes_fts WHERE node_id IN ("
        "  SELECT id FROM nodes WHERE version_id = :version_id"
        ")"
    )
    await session.execute(delete_sql, {"version_id": version_id})

    # Insert fresh entries
    insert_sql = text(
        "INSERT INTO nodes_fts (node_id, heading, body) "
        "SELECT id, heading, body FROM nodes WHERE version_id = :version_id"
    )
    result = await session.execute(insert_sql, {"version_id": version_id})
    await session.commit()

    count = result.rowcount if result.rowcount else 0
    logger.info("fts5_index_synced", version_id=version_id, node_count=count)
    return count


async def remove_fts5_entries(session: AsyncSession, node_ids: list[str]) -> None:
    """Remove specific nodes from the FTS5 index."""
    if not node_ids:
        return

    # Use parameterized delete
    placeholders = ", ".join([f":id_{i}" for i in range(len(node_ids))])
    params = {f"id_{i}": nid for i, nid in enumerate(node_ids)}

    delete_sql = text(f"DELETE FROM nodes_fts WHERE node_id IN ({placeholders})")
    await session.execute(delete_sql, params)
    await session.commit()
