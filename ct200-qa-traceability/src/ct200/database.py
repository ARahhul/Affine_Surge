"""Consolidated database layer — SQLAlchemy models, engine, and data access.

Schema:
  documents → versions → nodes (with position_index for deterministic ordering)
                       → selections (version-pinned, immutable)
                       → generations (QA test case generation records)

SQLite configured with WAL mode and synchronous=NORMAL for write performance.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    create_engine,
    event,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


# --- SQLite PRAGMAs on every connection ---

@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA cache_size=-64000")  # 64MB page cache
    cursor.close()


# --- ORM Models ---

class Document(Base):
    __tablename__ = "documents"
    id = Column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)
    versions = relationship("Version", back_populates="document", order_by="Version.version_number")


class Version(Base):
    __tablename__ = "versions"
    id = Column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(Text, ForeignKey("documents.id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    content_hash = Column(Text, nullable=False)
    ingested_at = Column(Text, nullable=False)
    parser_report_json = Column(Text)
    block_count = Column(Integer, default=0)
    mapped_block_count = Column(Integer, default=0)
    document = relationship("Document", back_populates="versions")
    nodes = relationship("Node", back_populates="version", order_by="Node.position_index")
    __table_args__ = (
        Index("ix_version_doc_hash", "document_id", "content_hash", unique=True),
    )


class Node(Base):
    __tablename__ = "nodes"
    id = Column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    version_id = Column(Text, ForeignKey("versions.id"), nullable=False)
    parent_id = Column(Text, ForeignKey("nodes.id"), nullable=True)
    heading = Column(Text, nullable=False, default="")
    level = Column(Integer, nullable=False, default=0)
    body = Column(Text, nullable=False, default="")
    content_hash = Column(Text, nullable=False)
    position_index = Column(Integer, nullable=False)
    lineage_id = Column(Text, nullable=False)
    match_strategy = Column(Text, default="new")
    confidence_score = Column(Float, default=1.0)
    version = relationship("Version", back_populates="nodes")
    children = relationship("Node", back_populates="parent", foreign_keys=[parent_id])
    parent = relationship("Node", remote_side=[id], back_populates="children")
    __table_args__ = (
        Index("ix_node_version", "version_id"),
        Index("ix_node_lineage", "lineage_id"),
        Index("ix_node_position", "version_id", "position_index", unique=True),
    )


class Selection(Base):
    __tablename__ = "selections"
    id = Column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    version_id = Column(Text, ForeignKey("versions.id"), nullable=False)
    node_ids_json = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)
    label = Column(Text, default="")


class Generation(Base):
    __tablename__ = "generations"
    id = Column(Text, primary_key=True, default=lambda: str(uuid.uuid4()))
    selection_id = Column(Text, ForeignKey("selections.id"), nullable=False)
    status = Column(Text, nullable=False, default="pending")
    source_hashes_json = Column(Text, nullable=False)
    output_json = Column(Text, nullable=True)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    model_id = Column(Text, nullable=False, default="")
    error_message = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)


# --- Engine & Session Factory ---

_engine = None
_SessionLocal = None


def get_engine(database_url: str = "sqlite:///data/ct200.db"):
    """Create or return the singleton engine."""
    global _engine
    if _engine is None:
        _engine = create_engine(database_url, echo=False)
        Base.metadata.create_all(_engine)
        # Create FTS5 virtual table
        with _engine.connect() as conn:
            conn.execute(text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5("
                "node_id UNINDEXED, heading, body, "
                "tokenize='porter unicode61')"
            ))
            conn.commit()
    return _engine


def get_session(database_url: str = "sqlite:///data/ct200.db") -> Session:
    """Create a new database session."""
    global _SessionLocal
    if _SessionLocal is None:
        engine = get_engine(database_url)
        _SessionLocal = sessionmaker(bind=engine)
    return _SessionLocal()


def reset_engine():
    """Reset for testing."""
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None


# --- Data Access Helpers ---

def compute_content_hash(heading: str, body: str) -> str:
    """SHA-256 of heading+body for deterministic content identification."""
    return hashlib.sha256(f"{heading}\n{body}".encode()).hexdigest()


def ingest_document(session: Session, name: str, pdf_bytes: bytes, nodes_data: list[dict]) -> dict:
    """Ingest a document version with idempotency check.
    
    Returns dict with document_id, version_id, is_new, version_number.
    """
    content_hash = hashlib.sha256(pdf_bytes).hexdigest()
    now = datetime.now(timezone.utc).isoformat()

    # Find or create document by name
    doc = session.query(Document).filter_by(name=name).first()
    if not doc:
        doc = Document(id=str(uuid.uuid4()), name=name, created_at=now)
        session.add(doc)
        session.flush()

    # Idempotency: check if this exact content already exists
    existing = session.query(Version).filter_by(
        document_id=doc.id, content_hash=content_hash
    ).first()
    if existing:
        return {"document_id": doc.id, "version_id": existing.id,
                "version_number": existing.version_number, "is_new": False}

    # Create new version
    latest = session.query(Version).filter_by(document_id=doc.id)\
        .order_by(Version.version_number.desc()).first()
    version_number = (latest.version_number + 1) if latest else 1
    version_id = str(uuid.uuid4())

    version = Version(
        id=version_id, document_id=doc.id, version_number=version_number,
        content_hash=content_hash, ingested_at=now,
        block_count=len(nodes_data), mapped_block_count=len(nodes_data),
    )
    session.add(version)
    session.flush()

    # Persist nodes with position_index for deterministic ordering
    # Use bulk insert for O(1) round-trips instead of N individual adds
    node_objects = []
    for idx, node_data in enumerate(nodes_data):
        node_objects.append(Node(
            id=node_data.get("id", str(uuid.uuid4())),
            version_id=version_id,
            parent_id=node_data.get("parent_id"),
            heading=node_data.get("heading", ""),
            level=node_data.get("level", 0),
            body=node_data.get("body", ""),
            content_hash=node_data.get("content_hash", ""),
            position_index=idx,
            lineage_id=node_data.get("lineage_id", str(uuid.uuid4())),
            match_strategy=node_data.get("match_strategy", "new"),
            confidence_score=node_data.get("confidence_score", 1.0),
        ))
    session.bulk_save_objects(node_objects)

    session.commit()
    return {"document_id": doc.id, "version_id": version_id,
            "version_number": version_number, "is_new": True}
