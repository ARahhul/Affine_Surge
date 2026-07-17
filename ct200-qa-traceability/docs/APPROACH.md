# Approach: CT200 QA Traceability System

## Data Model

The system follows a strict hierarchy:

```
Document → Version → Node (hierarchical tree, stored flat with parent_id + position_index)
                   → Selection (immutable version-pinned subset of nodes)
                   → Generation (QA test cases generated from a selection)
```

**Document** is identified by uploaded filename. Each unique PDF content creates a new **Version** (idempotent on byte-level SHA-256). Versions contain ordered **Nodes** — each with a `lineage_id` for cross-version tracking. **Selections** pin specific nodes at a specific version. **Generations** store LLM output alongside `source_hashes` (node_id → content_hash at generation time) to enable staleness detection.

## Parser Irregularities Found

Four categories emerged during development against the CT200 manual:

1. **Duplicate headings** — The PDF contains repeated section titles (e.g., "Caution" appears multiple times). The parser preserves each as a distinct node and emits a diagnostic warning rather than merging or deduplicating.

2. **Skipped heading levels** — H2 jumps to H4 in some sections. The tree engine assigns to the nearest valid ancestor rather than fabricating an H3, maintaining structural truth over strict hierarchy.

3. **Numbered lists confused with headings** — Lines like "1. Remove cover" match heading numbering patterns. Classification uses font size + weight + length + punctuation to disambiguate, but edge cases remain and are retained as body content.

4. **Cover page metadata** — Title page, revision info, and copyright blocks are detected as repeated-content or metadata patterns and filtered by the header/footer stripper before tree construction.

## Versioning Strategy

The lineage matcher uses a strict three-tier strategy (exact → heading → positional):

| Tier | Signal | Confidence | Risk |
|------|--------|-----------|------|
| 1. Exact hash | SHA-256 of heading+body | 1.0 | None — content is identical |
| 2. Heading match | Same heading text + depth similarity | 0.7–0.95 | Renames break this tier |
| 3. Positional | Same depth, closest order_index | 0.5–0.7 | **Silently mismatches when sections are reordered** |

The failure mode of Tier 3 is the system's most dangerous silent error: if sections are reordered between versions, positional matching may link unrelated content with moderate confidence, and the system will not error. Matches below the 0.75 threshold surface as `needs_review` status, but above-threshold positional matches auto-accept.

## LLM Prompt Design

System/user message separation enforces a structural injection boundary:

- **System message** contains ONLY generation instructions and the JSON output schema. It never includes document content.
- **User message** contains ONLY document content wrapped in `<DOCUMENT_CONTENT>...</DOCUMENT_CONTENT>` delimiters.

JSON schema validation uses Pydantic with one retry: if the first response fails validation, the same prompt is re-sent once. After two failures, the generation is marked `failed` with `NIMSchemaError`. Rate limiting (40 RPM default) and exponential backoff on transient errors protect against cascade failures.

## What I'd Do Differently

1. **Wire lineage matching into ingestion from the start** — it was developed as a library component and only integrated into the ingestion route late. This led to the "lineage_id stays as generated UUID" behavior for all previously-ingested data.

2. **Add a human-review queue for low-confidence matches** — currently `needs_review` status is stored but there's no workflow to surface it. A review endpoint with approve/reject would close the loop.

3. **Use PostgreSQL from the start** — SQLite is fine for single-instance local development, but WAL mode doesn't help with concurrent writes from multiple workers. The migration path is clear (SQLAlchemy makes it trivial) but should have been the default.

4. **Structured parser diagnostics as first-class API output** — parser warnings are accumulated but not yet returned by the ingestion response. They should be persisted with each version and queryable.

## Failure Mode Analysis

See [docs/decision_log.md](decision_log.md) for the honest answers about what silently goes wrong, where simplicity was chosen over correctness, and unhandled inputs.
