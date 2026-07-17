# ADR 0001: SQLite over PostgreSQL

## Status
Accepted

## Context
The CT200 QA Traceability System is a single-instance tool for parsing and versioning technical manuals. It does not require horizontal scaling, connection pooling, or concurrent multi-writer workloads.

## Decision
Use SQLite with WAL mode and synchronous=NORMAL as the sole persistence backend, accessed through SQLAlchemy's synchronous session API.

## Consequences
- Zero operational overhead: no database server to provision, configure, or monitor.
- WAL mode provides concurrent read performance suitable for the expected workload.
- No horizontal write scaling — acceptable for a single-instance QA tool.
- Schema is portable to PostgreSQL via SQLAlchemy if deployment requirements change.
- FTS5 is SQLite-specific; migration would require replacing it with PostgreSQL's tsvector or an external search index.
