# Phase Log

Honest status of each planned phase, relative to the original spec (removed from this repo; scope was descoped mid-build).

## Shipped

- **Ingestion & parsing** — PyMuPDF extraction, header/footer stripping, multi-signal heading/table/list classification. Fully implemented and tested.
- **Tree reconstruction & hashing** — Deterministic SHA-256 content hashing, structural validation, multi-signal hierarchy assignment with parser warnings. Fully implemented and tested.
- **Versioning** — Append-only versions, idempotent re-ingestion by content hash. Fully implemented and tested.
- **Browse, node history, selections** — REST endpoints for node browsing, lineage history, and immutable version-pinned selections. Fully implemented and tested.

## Descoped (planned in the original spec, not built)

- **Auth & rate limiting** — No middleware exists. `.env.example` documents `AUTH_SECRET_KEY` and rate-limit env vars as a reminder; nothing reads them today.
- **FTS5 search endpoint** — The virtual table is created in `database.py` but never indexed or queried. No `/search` route exists.
- **NIM-based QA generation** — `src/ct200/generation/` has a client and prompt templates but no HTTP route wires them up.
- **Impact / staleness analysis** — No analyzer or endpoint exists in the current API.

## Why

Scope was cut to ship a small, fully-tested ingestion+browse+versioning core rather than a partially-tested everything. The four descoped items are each a self-contained follow-up, not a redesign.
