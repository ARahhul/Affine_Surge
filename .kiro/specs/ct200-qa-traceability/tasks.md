# Implementation Plan: CT200 QA Traceability System

## Overview

This implementation plan follows the 10-phase engineering spec for the CT200 QA Traceability System — a Python/FastAPI backend that parses CT200 technical PDFs into versioned document trees, generates QA test cases via NVIDIA NIM (GLM-5.2), and detects staleness. Each phase builds incrementally on prior phases, with checkpoints for validation.

## Tasks

- [x] 1. Phase 1 — Engineering Foundation
  - [x] 1.1 Create project skeleton with pyproject.toml and folder structure
    - Initialize `ct200-qa-traceability/` with the full Clean Architecture folder layout (src/ct200/, tests/, docs/, alembic/)
    - Configure `pyproject.toml` with Python 3.12, FastAPI, SQLAlchemy 2.x, Pydantic v2, structlog, slowapi, PyMuPDF, Hypothesis, pytest, Ruff, Black, MyPy
    - Create `__init__.py` files for all packages
    - Create `.env.example` documenting all configuration variables
    - _Requirements: 1.1, 1.4_

  - [x] 1.2 Implement Pydantic Settings configuration loader
    - Create `src/ct200/config.py` with `BaseSettings` class loading all env vars (DATABASE_URL, NVIDIA_NIM_API_KEY, AUTH_SECRET_KEY, rate limits, timeouts, etc.)
    - Add startup validation that rejects missing required variables with clear error messages
    - _Requirements: 1.4, CP-1.2_

  - [x] 1.3 Implement structured JSON logging with correlation IDs
    - Create `src/ct200/transport/middleware/correlation.py` injecting X-Correlation-ID into request context
    - Configure structlog for JSON output with correlation_id, timestamp, level, logger bound to each entry
    - Ensure correlation ID propagates through the full request lifecycle
    - _Requirements: 1.3, 11.1, 11.2, CP-1.1_

  - [x] 1.4 Implement health, readiness, and metrics endpoints
    - Create `src/ct200/transport/routers/health.py` with GET /health (liveness), GET /ready (DB check with 5s timeout), GET /metrics (Prometheus format)
    - Implement Prometheus instrumentation middleware for request counts, latencies, error rates
    - _Requirements: 1.5, 1.6, 1.7, 11.4, 11.5_

  - [x] 1.5 Implement FastAPI app factory with dependency injection
    - Create `src/ct200/main.py` with app factory wiring middleware stack (correlation → auth → rate limit → metrics → error handler)
    - Create `src/ct200/dependencies.py` with DI provider functions for all services
    - Ensure no service class directly instantiates its own dependencies
    - _Requirements: 1.2_

  - [x] 1.6 Implement domain exception hierarchy and global error handler
    - Create `src/ct200/domain/exceptions.py` with CT200Error base and subclasses (ValidationError, NotFoundError, ParseError, TimeoutError, GenerationError, AuthenticationError, RateLimitError)
    - Create `src/ct200/transport/middleware/error_handler.py` mapping domain exceptions to structured JSON responses with correlation_id
    - _Requirements: 1.3_

  - [x] 1.7 Set up CI pipeline configuration
    - Create `.github/workflows/ci.yml` running Ruff lint, Black format check, MyPy --strict, pytest, and pip-audit
    - Configure build to fail on any violation
    - _Requirements: 1.8, 1.9, 12.7_

  - [x] 1.8 Create Dockerfile and docker-compose.yml
    - Write multi-stage Dockerfile building the app and exposing /health
    - Create docker-compose.yml for local development
    - _Requirements: 10.6, CP-10.1_

  - [ ]* 1.9 Write unit tests for configuration and health endpoints
    - Test config loader rejects missing required env vars
    - Test /health returns 200, /ready returns 503 when DB unavailable, /metrics returns Prometheus format
    - Test correlation ID appears in all log entries for a single request
    - _Requirements: 1.5, 1.6, 11.5, CP-1.1, CP-1.2_

- [x] 2. Checkpoint — Foundation validation
  - Ensure all tests pass, ask the user if questions arise.
  - push to git based on phase 1 

- [x] 3. Phase 2 — PDF Intelligence

  - [x] 3.1 Implement PDF parser with PyMuPDF
    - Create `src/ct200/infrastructure/parser/pymupdf_parser.py` implementing IParser protocol
    - Extract headings, tables, numbered lists, and body text preserving original ordering
    - Implement magic-byte validation (reject non-PDF), file size check (50MB limit), and configurable timeout (default 120s)
    - Implement multi-column layout reconstruction (left-to-right, top-to-bottom)
    - _Requirements: 2.1, 2.3, 2.7, 2.8, 2.9, 2.10, 12.4_

  - [x] 3.2 Implement repeated header/footer detection and stripping
    - Detect elements appearing identically on 2+ consecutive pages
    - Strip repeated elements from extracted content
    - _Requirements: 2.2_

  - [x] 3.3 Implement markdown renderer
    - Create `src/ct200/infrastructure/parser/markdown_renderer.py`
    - Reconstruct markdown from parsed content using headings, tables, lists, paragraph blocks
    - Ensure deterministic output (same input produces byte-identical markdown)
    - _Requirements: 2.4, CP-2.3_

  - [x] 3.4 Implement parser reporting and reconciliation
    - Generate `parser_report.json` with extraction statistics (pages, headings, tables, lists, body blocks)
    - Generate `validation_report.json` with structural validation results (ordering violations, stripped headers, multi-column pages)
    - Compute reconciliation count (extracted vs mapped blocks)
    - _Requirements: 2.5, 2.6, CP-2.2_

  - [x] 3.5 Implement parser hardening (fail-closed behavior)
    - Implement pathological input detection (nesting > 20 levels, page content > 50MB)
    - Ensure parser never produces partial/corrupted output on any error path
    - Return structured error responses for all failure cases
    - _Requirements: 2.10, 2.9_

  - [ ]* 3.6 Write property test for Parse Round-Trip (Property 1)
    - **Property 1: Parse Round-Trip**
    - Test that parse → markdown → re-parse produces structurally equivalent tree
    - Use Hypothesis strategies generating random document structures
    - **Validates: Requirements 2.11, 2.4**

  - [ ]* 3.7 Write property test for Non-PDF Rejection (Property 2)
    - **Property 2: Non-PDF Rejection**
    - Test that any byte sequence without PDF magic bytes is rejected
    - Use Hypothesis `st.binary()` strategy
    - **Validates: Requirements 2.8, 12.4**

  - [ ]* 3.8 Write property test for Header/Footer Stripping (Property 3)
    - **Property 3: Header/Footer Stripping**
    - Test repeated blocks on consecutive pages are stripped while preserving unique content
    - **Validates: Requirements 2.2**

  - [ ]* 3.9 Write property test for Parser Report Completeness (Property 4)
    - **Property 4: Parser Report Completeness**
    - Test block_count >= mapped_block_count >= 0 for all parsed documents
    - **Validates: Requirements 2.5, 2.6**

- [x] 4. Checkpoint — PDF Parser validation
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Phase 3 — Tree Engine

  - [x] 5.1 Implement domain entities and value objects
    - Create `src/ct200/domain/entities.py` with DocumentNode, DocumentTree, LineageMatch, ParsedContent, etc.
    - Create `src/ct200/domain/value_objects.py` with ContentHash, LineageID, ConfidenceScore
    - Implement Pydantic v2 validation for all entities
    - _Requirements: 3.1_

  - [x] 5.2 Implement tree construction engine
    - Create `src/ct200/infrastructure/tree/tree_engine.py` implementing ITreeEngine protocol
    - Build hierarchical tree from parsed content assigning heading, body, depth (0-10), parent, children, parsed_number, order_index, lineage_id placeholder, content_hash
    - Implement duplicate heading disambiguation via unique (parent, heading, order_index) tuple
    - Handle skipped heading levels by inserting under nearest valid ancestor
    - Preserve document ordering via order_index based on source sequence
    - Classify numbered-list items as body content, not separate nodes
    - Reconstruct multi-page tables as single coherent nodes
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 5.3 Implement tree validation
    - Validate single-parent rule for every non-root node
    - Validate no cycles (parent pointer traversal terminates at root)
    - Validate depth consistency (node.depth == parent.depth + 1)
    - Validate contiguous zero-based sibling order indices
    - Reject invalid trees with error indicating which rule failed and offending node
    - _Requirements: 3.7, 3.8, 3.9, 3.10, 3.11_

  - [x] 5.4 Implement content hash computation
    - Compute SHA-256 hash of heading+body concatenation for each node
    - Ensure deterministic: identical content always produces same hash
    - _Requirements: 3.12, CP-3.2_

  - [ ]* 5.5 Write property test for Tree Structural Invariants (Property 5)
    - **Property 5: Tree Structural Invariants**
    - Verify all invariants hold for any tree produced by Tree Engine
    - Use Hypothesis strategies generating random parsed content with varying depth/structure
    - **Validates: Requirements 3.7, 3.8, 3.9, 3.10, 3.1**

  - [ ]* 5.6 Write property test for Heading Disambiguation (Property 6)
    - **Property 6: Heading Disambiguation**
    - Test duplicate headings get distinct identities based on positional context
    - **Validates: Requirements 3.2**

  - [ ]* 5.7 Write property test for Depth-Skip Handling (Property 7)
    - **Property 7: Depth-Skip Handling**
    - Test heading level skips maintain structural consistency
    - **Validates: Requirements 3.3**

  - [ ]* 5.8 Write property test for Document Order Preservation (Property 8)
    - **Property 8: Document Order Preservation**
    - Test order_index reflects original document ordering regardless of source numbering
    - **Validates: Requirements 3.4, 2.1**

  - [ ]* 5.9 Write property test for List-Item Classification (Property 9)
    - **Property 9: List-Item Classification**
    - Test numbered-list items resembling headings are classified as body content
    - **Validates: Requirements 3.5**

- [x] 6. Checkpoint — Tree Engine validation
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Phase 4 — Persistence

  - [x] 7.1 Implement SQLAlchemy ORM models and database engine
    - Create `src/ct200/infrastructure/database/engine.py` with async engine, session factory, WAL mode, FK enforcement
    - Create `src/ct200/infrastructure/database/models.py` with DocumentModel, VersionModel, NodeModel, SelectionModel, GenerationModel
    - Add all indexes (ix_versions_doc_hash, ix_nodes_version, ix_nodes_lineage, ix_nodes_parent_order)
    - _Requirements: 4.1, 4.2_

  - [x] 7.2 Set up Alembic migrations
    - Configure `alembic/env.py` for async SQLAlchemy
    - Create initial migration creating all tables with FTS5 virtual table for nodes_fts
    - _Requirements: 4.1, 4.2_

  - [x] 7.3 Implement repository layer
    - Create `src/ct200/infrastructure/database/repositories/` with DocumentRepository, VersionRepository, NodeRepository, SelectionRepository, GenerationRepository
    - Implement all IRepository protocol methods
    - Implement content-hash based idempotent version check
    - Implement single-transaction node bulk creation
    - _Requirements: 4.3, 4.4, 4.5, 4.6, CP-4.1, CP-4.2, CP-4.3_

  - [x] 7.4 Implement ingestion API endpoint
    - Create `src/ct200/transport/routers/ingestion.py` with POST /api/v1/documents (multipart PDF upload)
    - Create `src/ct200/application/ingestion.py` with IngestDocumentUseCase orchestrating parse → tree → version → persist
    - Wire DI for parser, tree engine, repositories
    - _Requirements: 2.1, 4.3, 4.6_

  - [x] 7.5 Implement authentication middleware
    - Create `src/ct200/transport/middleware/auth.py` validating bearer tokens against AUTH_SECRET_KEY
    - Skip auth for /health, /ready, /metrics, /docs endpoints
    - Return HTTP 401 with structured error on invalid/missing credentials
    - _Requirements: 12.1, CP-12.1_

  - [x] 7.6 Implement rate limiting middleware
    - Create `src/ct200/transport/middleware/rate_limit.py` using slowapi
    - Configure per-client limits on ingestion (default 10/min) and generation (default 40/min) endpoints
    - Return HTTP 429 with Retry-After header on limit exceeded
    - _Requirements: 12.2, 12.3, CP-12.2_

  - [ ]* 7.7 Write property test for Persistence Round-Trip (Property 10)
    - **Property 10: Persistence Round-Trip**
    - Test persist(tree) → reload produces structurally equal tree
    - Use Hypothesis strategies generating random valid document trees
    - **Validates: Requirements 4.4, 4.6**

  - [ ]* 7.8 Write property test for Idempotent Ingestion (Property 11)
    - **Property 11: Idempotent Ingestion**
    - Test ingesting same content twice results in exactly one version record
    - **Validates: Requirements 4.3**

- [x] 8. Checkpoint — Persistence validation
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Phase 5 — Versioning

  - [x] 9.1 Implement three-tier lineage matching strategy
    - Create `src/ct200/infrastructure/versioning/lineage_matcher.py` implementing IVersioningEngine protocol
    - Tier 1: Exact Content_Hash match (confidence = 1.0)
    - Tier 2: Parent-lineage + heading match (confidence based on similarity)
    - Tier 3: Positional fallback (lowest confidence)
    - Assign match_strategy and confidence_score to each node
    - _Requirements: 5.1, 5.2, CP-5.1_

  - [x] 9.2 Implement needs_review flagging for low-confidence matches
    - When confidence_score < configurable threshold (default 0.75), assign needs_review status
    - Never auto-accept low-confidence matches
    - _Requirements: 5.3, CP-5.2_

  - [x] 9.3 Implement version immutability and diff computation
    - Ensure new version ingestion never mutates previous version records or nodes
    - Create `src/ct200/application/versioning.py` with DiffVersionsUseCase
    - Compute diff returning added, removed, modified nodes with changed fields
    - Classify unmatched new nodes as "added" and unmatched old nodes as "removed"
    - _Requirements: 5.4, 5.5, 5.6, 5.7, CP-5.3_

  - [ ]* 9.4 Write property test for Lineage Strategy Selection (Property 12)
    - **Property 12: Lineage Strategy Selection**
    - Test exact matches receive confidence 1.0, all nodes assigned a valid strategy
    - Use Hypothesis generating pairs of trees with controlled mutations
    - **Validates: Requirements 5.1, 5.2**

  - [ ]* 9.5 Write property test for Low-Confidence Review Flag (Property 13)
    - **Property 13: Low-Confidence Review Flag**
    - Test all matches below threshold get needs_review, never matched
    - **Validates: Requirements 5.3**

  - [ ]* 9.6 Write property test for Version Immutability (Property 14)
    - **Property 14: Version Immutability**
    - Test ingesting new version does not mutate any field of previous version or its nodes
    - **Validates: Requirements 5.4**

- [x] 10. Checkpoint — Versioning validation
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Phase 6 — Browse and Search

  - [x] 11.1 Implement browse API endpoints
    - Create `src/ct200/transport/routers/browse.py` with GET /api/v1/documents/{id}/versions/{vid}/tree (browse hierarchy)
    - Create `src/ct200/application/browse.py` with BrowseTreeUseCase
    - Return nodes with heading, depth, order_index, content_hash, child_count, scoped to specified version
    - Implement single-node retrieval by ID returning full node details including body, parent, children, lineage_id
    - Return 404 for non-existent node IDs
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 11.2 Implement FTS5 full-text search
    - Create `src/ct200/infrastructure/search/fts5_search.py` implementing search across heading and body
    - Create `src/ct200/transport/routers/search.py` with GET /api/v1/search
    - Create `src/ct200/application/search.py` with SearchNodesUseCase
    - Scope results to specified document version, rank by relevance
    - Reject queries shorter than 2 characters with error response
    - _Requirements: 6.4, 6.5, CP-6.2, CP-6.3_

  - [x] 11.3 Implement pagination for browse and search
    - Add pagination support with default page_size=20, max page_size=100
    - Include total count, page metadata, version ID, node count, content_hash, and per-request latency in responses
    - _Requirements: 6.6, 6.7, CP-6.1_

  - [x] 11.4 Implement change detection in browse/search responses
    - Expose change detection info for nodes whose content_hash differs between versions
    - Include previous_hash, current_hash, and change_type (added, modified, removed)
    - _Requirements: 6.8, CP-6.3_

  - [ ]* 11.5 Write property test for FTS Search Recall (Property 15)
    - **Property 15: FTS Search Recall**
    - Test that any indexed node containing a search term appears in results
    - **Validates: Requirements 6.4**

  - [ ]* 11.6 Write property test for Pagination Consistency (Property 16)
    - **Property 16: Pagination Consistency**
    - Test iterating all pages returns every node exactly once, no duplicates or omissions
    - **Validates: Requirements 6.6**

  - [ ]* 11.7 Write property test for Change Detection (Property 17)
    - **Property 17: Change Detection**
    - Test nodes with differing content_hash between versions expose change info
    - **Validates: Requirements 6.8**

- [x] 12. Checkpoint — Browse & Search validation
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 13. Phase 7 — Selection and Generation

  - [~] 13.1 Implement selection service and API
    - Create `src/ct200/transport/routers/selection.py` with POST /api/v1/selections and GET /api/v1/selections/{id}
    - Create `src/ct200/application/selection.py` with CreateSelectionUseCase
    - Create immutable, version-pinned selections referencing specific nodes
    - Validate all node IDs exist in the specified version; reject if zero nodes or invalid IDs
    - Ensure selections are write-once (no mutation after creation)
    - _Requirements: 7.1, 7.2, CP-7.1_

  - [~] 13.2 Implement NVIDIA NIM client with retry logic
    - Create `src/ct200/infrastructure/generation/nim_client.py` with HTTP client for NIM API
    - Implement JSON mode request, response parsing, token count extraction
    - Implement retry: on schema validation failure retry once, on transient HTTP errors retry with exponential backoff (max 3)
    - Enforce hard timeout of 60 seconds
    - Enforce rate limit of 40 requests/minute against NIM (configurable)
    - _Requirements: 7.3, 7.6, 7.8, 7.9, CP-7.3_

  - [~] 13.3 Implement prompt templates with injection hygiene
    - Create `src/ct200/infrastructure/generation/prompt_templates.py`
    - Structurally separate system instructions from document content in prompts
    - Ensure document content cannot alter system instruction section
    - _Requirements: 7.3, 12.6, CP-7.4_

  - [~] 13.4 Implement generation service and API
    - Create `src/ct200/transport/routers/generation.py` with POST /api/v1/generations and GET /api/v1/generations/{id}
    - Create `src/ct200/application/generation.py` with GenerateTestCasesUseCase
    - Validate NIM response against Pydantic schema; retry once on failure
    - On success: create GenerationRecord with status=completed, QA test cases, source_hashes, token counts
    - On double failure: create GenerationRecord with status=generation_failed and error details
    - On timeout/network failure: create terminal generation_failed record
    - Record input/output token counts from NIM response
    - _Requirements: 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.10, CP-7.2_

  - [~] 13.5 Implement per-client rate limiting on generation endpoint
    - Configure slowapi with default 10 requests/minute per client on generation endpoint
    - _Requirements: 7.11, 12.2_

  - [ ]* 13.6 Write property test for Selection Immutability (Property 18)
    - **Property 18: Selection Immutability**
    - Test that after creation, selection version_id and node_ids remain constant
    - **Validates: Requirements 7.1**

  - [ ]* 13.7 Write property test for Generation Schema Validation (Property 19)
    - **Property 19: Generation Schema Validation**
    - Test valid JSON conforming to schema is accepted, invalid JSON is rejected and triggers retry/failure
    - Use Hypothesis generating random valid and invalid JSON structures
    - **Validates: Requirements 7.4**

- [~] 14. Checkpoint — Selection & Generation validation
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 15. Phase 8 — Impact Analysis

  - [~] 15.1 Implement impact analyzer
    - Create `src/ct200/infrastructure/impact/analyzer.py` implementing IImpactAnalyzer protocol
    - Compare each source_hash in a GenerationRecord against current content_hash of matching lineage_id node in latest version
    - Return "current" if all hashes match, "stale" if any differ
    - List all changed/missing node lineage_ids with diff summary
    - Classify each change as "direct" (node content changed) or "descendant" (only children changed)
    - Report nodes whose lineage_id has no match in latest version as "missing"
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, CP-8.2, CP-8.3_

  - [~] 15.2 Implement impact analysis API endpoint
    - Create `src/ct200/transport/routers/impact.py` with GET /api/v1/impact/{generation_id}
    - Create `src/ct200/application/impact.py` with AnalyzeImpactUseCase
    - Ensure staleness is a computed view — never mutate historical generation records
    - _Requirements: 8.6, CP-8.1_

  - [ ]* 15.3 Write property test for Staleness Detection (Property 20)
    - **Property 20: Staleness Detection with Change Classification**
    - Test stale generations report all changed nodes with correct classification
    - Use Hypothesis generating generations with varying source hash changes
    - **Validates: Requirements 8.1, 8.2, 8.3**

  - [ ]* 15.4 Write property test for Generation Record Immutability (Property 21)
    - **Property 21: Generation Record Immutability**
    - Test impact analysis never mutates any field of the generation record
    - **Validates: Requirements 8.6**

- [~] 16. Checkpoint — Impact Analysis validation
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 17. Phase 9 — QA and Performance

  - [~] 17.1 Implement comprehensive unit test suite
    - Write 30+ unit tests covering domain logic, value objects, entity validation
    - Cover edge cases: empty documents, single-node trees, max depth, invalid IDs, corrupted data
    - Cover middleware chain, DI resolution, error mapping
    - _Requirements: 9.1_

  - [~] 17.2 Implement integration test suite
    - Write 20+ integration tests covering database operations, API endpoints, middleware
    - Test full ingestion pipeline end-to-end
    - Test search, browse, selection, generation flows
    - _Requirements: 9.1_

  - [~] 17.3 Implement hardening test suite
    - Write 10+ hardening tests for timeouts, size limits, pathological inputs, error paths
    - Test parser timeout enforcement, file size rejection, malformed PDF handling
    - Test rate limiting enforcement, auth rejection
    - _Requirements: 9.1_

  - [~] 17.4 Implement performance benchmarks with CI gate
    - Create `tests/hardening/test_benchmarks.py` with pytest-benchmark
    - Benchmark 10-page PDF parse (P95 < 2s over 20 runs)
    - Benchmark single node retrieval (P95 < 100ms)
    - Benchmark FTS query against 500+ nodes (P95 < 300ms)
    - Benchmark generation with mocked NIM (P95 < 15s)
    - Benchmark 200-page full ingest (P95 < 30s)
    - Configure CI to fail build if any threshold violated
    - _Requirements: 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, CP-9.1_

  - [ ]* 17.5 Write property test for No Content Leakage in Logs (Property 22)
    - **Property 22: No Content Leakage in Logs**
    - Test no raw document content appears in log entries at INFO level or below
    - **Validates: Requirements 11.3**

  - [~] 17.6 Verify test count minimums and CI regression gate
    - Confirm total test count ≥ 80 (30 unit, 20 integration, 10 hardening)
    - Ensure CI workflow runs all tests and benchmarks, fails on any regression
    - _Requirements: 9.1, CP-9.2_

- [~] 18. Checkpoint — QA & Performance validation
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 19. Phase 10 — Production Readiness

  - [~] 19.1 Create README with full project documentation
    - Document prerequisites and dependency versions
    - Document environment variable configuration
    - Document build and run commands
    - Document test execution instructions
    - _Requirements: 10.1_

  - [~] 19.2 Create APPROACH.md and Architecture Decision Records
    - Write `docs/APPROACH.md` explaining architectural decisions
    - Write ADR for technology choices (FastAPI, SQLite, SQLAlchemy, PyMuPDF)
    - Write ADR for NVIDIA NIM integration documenting rationale, data-flow, privacy considerations
    - Write at minimum 2 ADRs documenting trade-offs
    - _Requirements: 10.2, 10.7_

  - [~] 19.3 Create architecture diagrams
    - Create Mermaid diagrams in `docs/architecture.md` showing component relationships and request flow
    - Include high-level architecture, data flow, and database schema diagrams
    - _Requirements: 10.3_

  - [~] 19.4 Configure OpenAPI documentation and Swagger UI
    - Ensure FastAPI auto-generates OpenAPI spec from route definitions
    - Serve Swagger UI at /docs endpoint accessible without authentication
    - Verify documented endpoints reflect actual implemented API
    - _Requirements: 10.4, 10.8, CP-10.2_

  - [~] 19.5 Create known-limitations document
    - Write `docs/known-limitations.md` describing current constraints and boundaries
    - Document single-instance deployment limitation, in-memory rate limit state, SQLite concurrency bounds
    - _Requirements: 10.5_

  - [~] 19.6 Validate Dockerfile builds and serves /health
    - Verify Docker build succeeds and container starts
    - Verify container responds to GET /health with HTTP 200
    - _Requirements: 10.6, CP-10.1_

- [~] 20. Final Checkpoint — Production readiness review
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each phase builds on the previous phase — do not start Phase N+1 until Phase N checkpoint passes
- All code uses Python 3.12, FastAPI, SQLAlchemy 2.x, Pydantic v2, structlog, PyMuPDF, and Hypothesis
- Property tests use Hypothesis with minimum 100 iterations per property
- Performance benchmarks are CI-gated: exceeding thresholds fails the build
- The NVIDIA NIM integration requires a valid API key configured via environment variable
- All configuration is loaded from environment variables via Pydantic BaseSettings

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.6"] },
    { "id": 2, "tasks": ["1.3", "1.5", "1.7", "1.8"] },
    { "id": 3, "tasks": ["1.4", "1.9"] },
    { "id": 4, "tasks": ["3.1"] },
    { "id": 5, "tasks": ["3.2", "3.3", "3.5"] },
    { "id": 6, "tasks": ["3.4", "3.6", "3.7", "3.8", "3.9"] },
    { "id": 7, "tasks": ["5.1"] },
    { "id": 8, "tasks": ["5.2"] },
    { "id": 9, "tasks": ["5.3", "5.4"] },
    { "id": 10, "tasks": ["5.5", "5.6", "5.7", "5.8", "5.9"] },
    { "id": 11, "tasks": ["7.1"] },
    { "id": 12, "tasks": ["7.2"] },
    { "id": 13, "tasks": ["7.3", "7.5", "7.6"] },
    { "id": 14, "tasks": ["7.4", "7.7", "7.8"] },
    { "id": 15, "tasks": ["9.1"] },
    { "id": 16, "tasks": ["9.2", "9.3"] },
    { "id": 17, "tasks": ["9.4", "9.5", "9.6"] },
    { "id": 18, "tasks": ["11.1", "11.2"] },
    { "id": 19, "tasks": ["11.3", "11.4"] },
    { "id": 20, "tasks": ["11.5", "11.6", "11.7"] },
    { "id": 21, "tasks": ["13.1"] },
    { "id": 22, "tasks": ["13.2", "13.3"] },
    { "id": 23, "tasks": ["13.4", "13.5"] },
    { "id": 24, "tasks": ["13.6", "13.7"] },
    { "id": 25, "tasks": ["15.1"] },
    { "id": 26, "tasks": ["15.2"] },
    { "id": 27, "tasks": ["15.3", "15.4"] },
    { "id": 28, "tasks": ["17.1", "17.2", "17.3"] },
    { "id": 29, "tasks": ["17.4", "17.5"] },
    { "id": 30, "tasks": ["17.6"] },
    { "id": 31, "tasks": ["19.1", "19.2", "19.3", "19.5"] },
    { "id": 32, "tasks": ["19.4", "19.6"] }
  ]
}
```
