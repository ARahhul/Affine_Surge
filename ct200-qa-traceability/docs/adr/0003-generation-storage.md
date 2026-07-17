# ADR 0003: SQLite for generation output storage

## Status
Accepted

## Context
The original spec suggested considering a NoSQL/JSON store for generation output (QA test cases are variable-length JSON). The system already uses SQLite for all other persistence. Generation output is stored as a JSON text column in the `generations` table alongside metadata (status, token counts, source hashes).

## Decision
Store generation output as a JSON text column within the existing SQLite `generations` table rather than introducing a separate document store.

## Consequences
- No additional infrastructure: one database file contains all state.
- JSON column is queryable via SQLite's json_extract() if needed for future filtering.
- Generation output size is bounded by LLM max_tokens (4096 tokens ≈ 16KB text) — well within SQLite's row size limits.
- If generation volume grows beyond single-instance capacity, migration to PostgreSQL (with its native JSONB type) is straightforward.
- Trade-off: no schema validation at the storage layer for the JSON content — validation happens at the application layer via Pydantic before persistence.
