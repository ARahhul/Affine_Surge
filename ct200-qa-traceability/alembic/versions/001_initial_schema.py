"""Initial schema: documents, versions, nodes, selections, generations.

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables and FTS5 virtual table."""
    # Documents table
    op.create_table(
        "documents",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Versions table
    op.create_table(
        "versions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("ingested_at", sa.Text(), nullable=False),
        sa.Column("parser_report_json", sa.Text(), nullable=True),
        sa.Column("validation_report_json", sa.Text(), nullable=True),
        sa.Column("block_count", sa.Integer(), nullable=True),
        sa.Column("mapped_block_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_versions_doc_hash", "versions", ["document_id", "content_hash"], unique=True
    )

    # Nodes table
    op.create_table(
        "nodes",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("version_id", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.Text(), nullable=True),
        sa.Column("heading", sa.Text(), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("parsed_number", sa.Text(), server_default=""),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("lineage_id", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("match_strategy", sa.Text(), server_default="new"),
        sa.Column("confidence_score", sa.Float(), server_default="1.0"),
        sa.Column("lineage_status", sa.Text(), server_default="new"),
        sa.ForeignKeyConstraint(["version_id"], ["versions.id"]),
        sa.ForeignKeyConstraint(["parent_id"], ["nodes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nodes_version", "nodes", ["version_id"])
    op.create_index("ix_nodes_lineage", "nodes", ["lineage_id"])
    op.create_index("ix_nodes_parent_order", "nodes", ["parent_id", "order_index"], unique=True)

    # Selections table
    op.create_table(
        "selections",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("version_id", sa.Text(), nullable=False),
        sa.Column("node_ids_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), server_default=""),
        sa.ForeignKeyConstraint(["version_id"], ["versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Generations table
    op.create_table(
        "generations",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("selection_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("source_hashes_json", sa.Text(), nullable=False),
        sa.Column("output_json", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default="0"),
        sa.Column("output_tokens", sa.Integer(), server_default="0"),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["selection_id"], ["selections.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # FTS5 virtual table for full-text search on nodes
    op.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
            node_id,
            content,
            content='nodes',
            content_rowid='rowid'
        )
        """
    )


def downgrade() -> None:
    """Drop all tables."""
    op.execute("DROP TABLE IF EXISTS nodes_fts")
    op.drop_table("generations")
    op.drop_table("selections")
    op.drop_index("ix_nodes_parent_order", table_name="nodes")
    op.drop_index("ix_nodes_lineage", table_name="nodes")
    op.drop_index("ix_nodes_version", table_name="nodes")
    op.drop_table("nodes")
    op.drop_index("ix_versions_doc_hash", table_name="versions")
    op.drop_table("versions")
    op.drop_table("documents")
