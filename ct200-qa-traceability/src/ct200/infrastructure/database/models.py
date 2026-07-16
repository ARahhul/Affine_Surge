"""SQLAlchemy ORM models for the CT200 QA Traceability System.

Maps domain entities to normalized SQLite tables with proper indexes
and foreign key relationships.
"""

from sqlalchemy import Column, Float, ForeignKey, Index, Integer, Text, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable WAL mode and foreign keys on every SQLite connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class DocumentModel(Base):
    """Tracked document (e.g., the CT200 PDF)."""

    __tablename__ = "documents"

    id = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)

    versions = relationship(
        "VersionModel", back_populates="document", cascade="all, delete-orphan"
    )


class VersionModel(Base):
    """A specific ingested version of a document."""

    __tablename__ = "versions"

    id = Column(Text, primary_key=True)
    document_id = Column(Text, ForeignKey("documents.id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    content_hash = Column(Text, nullable=False)
    ingested_at = Column(Text, nullable=False)
    parser_report_json = Column(Text, nullable=True)
    validation_report_json = Column(Text, nullable=True)
    block_count = Column(Integer, nullable=True)
    mapped_block_count = Column(Integer, nullable=True)

    document = relationship("DocumentModel", back_populates="versions")
    nodes = relationship("NodeModel", back_populates="version", cascade="all, delete-orphan")
    selections = relationship(
        "SelectionModel", back_populates="version", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_versions_doc_hash", "document_id", "content_hash", unique=True),
    )


class NodeModel(Base):
    """A node in the hierarchical document tree."""

    __tablename__ = "nodes"

    id = Column(Text, primary_key=True)
    version_id = Column(Text, ForeignKey("versions.id"), nullable=False)
    parent_id = Column(Text, ForeignKey("nodes.id"), nullable=True)
    heading = Column(Text, nullable=False, default="")
    body = Column(Text, nullable=False, default="")
    depth = Column(Integer, nullable=False)
    parsed_number = Column(Text, default="")
    order_index = Column(Integer, nullable=False)
    lineage_id = Column(Text, nullable=False)
    content_hash = Column(Text, nullable=False)
    match_strategy = Column(Text, default="new")
    confidence_score = Column(Float, default=1.0)
    lineage_status = Column(Text, default="new")

    version = relationship("VersionModel", back_populates="nodes")
    children = relationship("NodeModel", back_populates="parent", foreign_keys=[parent_id])
    parent = relationship("NodeModel", remote_side=[id], back_populates="children")

    __table_args__ = (
        Index("ix_nodes_version", "version_id"),
        Index("ix_nodes_lineage", "lineage_id"),
        Index("ix_nodes_parent_order", "parent_id", "order_index", unique=True),
    )


class SelectionModel(Base):
    """An immutable, version-pinned selection of document nodes."""

    __tablename__ = "selections"

    id = Column(Text, primary_key=True)
    version_id = Column(Text, ForeignKey("versions.id"), nullable=False)
    node_ids_json = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)
    label = Column(Text, default="")

    version = relationship("VersionModel", back_populates="selections")
    generations = relationship(
        "GenerationModel", back_populates="selection", cascade="all, delete-orphan"
    )


class GenerationModel(Base):
    """A QA test case generation attempt record."""

    __tablename__ = "generations"

    id = Column(Text, primary_key=True)
    selection_id = Column(Text, ForeignKey("selections.id"), nullable=False)
    status = Column(Text, nullable=False, default="pending")
    source_hashes_json = Column(Text, nullable=False)
    output_json = Column(Text, nullable=True)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    model_id = Column(Text, nullable=False)
    retry_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)
    completed_at = Column(Text, nullable=True)

    selection = relationship("SelectionModel", back_populates="generations")
