# Requirements Document

## Introduction

The CT200 QA Traceability System is a production-quality backend that parses the CT200 technical PDF into a versioned document tree, generates QA test cases using NVIDIA NIM (GLM-5.2), and detects stale generations as documentation evolves. Security, latency, and failure-handling are first-class concerns. The system is built on Python 3.12, FastAPI, SQLAlchemy 2.x, SQLite with FTS5, Alembic, and Pydantic v2.

## Glossary

- **System**: The CT200 QA Traceability backend application
- **Parser**: The PDF parsing subsystem using PyMuPDF to extract structured content from CT200 PDF documents
- **Tree_Engine**: The subsystem that converts parsed content into a validated hierarchical document tree
- **Persistence_Layer**: The SQLAlchemy-based subsystem managing normalized SQLite storage of documents, versions, nodes, and selections
- **Versioning_Engine**: The subsystem responsible for lineage matching, confidence scoring, and version management
- **Search_Service**: The FTS5-based full-text search and browse subsystem
- **Selection_Service**: The subsystem managing immutable version-pinned node selections
- **Generation_Service**: The subsystem responsible for NVIDIA NIM (GLM-5.2) integration and QA test case generation
- **Impact_Analyzer**: The subsystem that compares stored generation source-hashes against latest lineage hashes to detect staleness
- **Health_Controller**: The endpoint subsystem providing liveness, readiness, and metrics endpoints
- **Auth_Guard**: The authentication middleware protecting all non-health endpoints
- **Rate_Limiter**: The slowapi-based middleware enforcing request rate limits on ingestion and generation endpoints
- **Document_Node**: A single unit in the hierarchical document tree containing heading, body, depth, parent, children, parsed number, order index, lineage_id, and content hash
- **Content_Hash**: A deterministic hash of a node's content used for change detection and idempotency
- **Lineage_ID**: A stable identifier that tracks a node across document versions
- **Confidence_Score**: A numeric value (0.0–1.0) representing the certainty of a lineage match between versions
- **Correlation_ID**: A unique request-scoped identifier attached to all log entries for tracing
- **Generation_Record**: A stored record of a QA test case generation attempt including status, token counts, and source hashes
- **Staleness**: A computed view indicating that a generation's source content has changed since the generation was created

## Requirements

### Requirement 1: Engineering Foundation

**User Story:** As a developer, I want a clean-architecture project skeleton with structured tooling, so that the codebase is maintainable, observable, and CI-ready from day one.

#### Acceptance Criteria

1. THE System SHALL use FastAPI as the HTTP framework, SQLAlchemy 2.x as the ORM, SQLite as the database engine, Alembic for migrations, and Pydantic v2 for data validation
2. THE System SHALL implement dependency injection for all service dependencies such that no service class directly instantiates its own repository or external client
3. THE System SHALL produce structured JSON logs using structlog with a Correlation_ID attached to every log entry within a request lifecycle
4. THE System SHALL load all configuration from environment variables and never embed secrets in source code
5. THE Health_Controller SHALL expose a GET /health endpoint that returns HTTP 200 with a JSON body indicating service status when the process is alive
6. THE Health_Controller SHALL expose a GET /ready endpoint that returns HTTP 200 only when a lightweight database query completes successfully within 5 seconds, and HTTP 503 otherwise
7. THE Health_Controller SHALL expose a GET /metrics endpoint returning Prometheus-format metrics including request counts, latencies, and error rates
8. THE System SHALL enforce linting via Ruff, formatting via Black, and strict type checking via MyPy (--strict mode) in the CI pipeline, failing the build on any violation
9. THE System SHALL run pytest, dependency vulnerability scanning via pip-audit, and all static checks in the CI workflow, failing the build if any check reports errors or test failures

#### Correctness Properties

- **CP-1.1**: For any valid request, the structured log output SHALL contain exactly one Correlation_ID value that matches across all log entries produced during that request lifecycle
- **CP-1.2**: For any configuration value loaded at startup, the System SHALL reject startup with a clear error if a required environment variable is missing or fails Pydantic validation

### Requirement 2: PDF Parsing

**User Story:** As a QA engineer, I want the system to parse the CT200 technical PDF into structured content, so that document sections are accurately extracted for tree building and test generation.

#### Acceptance Criteria

1. WHEN a CT200 PDF is uploaded, THE Parser SHALL extract headings, tables, numbered lists, and body text while preserving their original ordering
2. WHEN the PDF contains repeated running headers or footers, THE Parser SHALL detect elements appearing identically on two or more consecutive pages and strip those repeated elements from extracted content
3. WHEN the PDF contains multi-column layouts, THE Parser SHALL reconstruct content in left-to-right, top-to-bottom reading order within each page
4. WHEN parsing completes, THE Parser SHALL produce a reconstructed markdown representation of the document content using headings, tables, lists, and paragraph blocks corresponding to the extracted elements
5. WHEN parsing completes, THE Parser SHALL produce a parser_report.json containing extraction statistics (total pages processed, count of headings extracted, count of tables extracted, count of list items extracted, count of body text blocks extracted) and a validation_report.json containing structural validation results (count of ordering violations detected, count of repeated headers stripped, count of multi-column pages reconstructed)
6. WHEN parsing completes, THE Parser SHALL report a content reconciliation count comparing the number of extracted content blocks to the number of blocks successfully mapped into the markdown output
7. IF the uploaded file exceeds 50 megabytes, THEN THE Parser SHALL reject the upload and return an error response indicating the file size limit was exceeded
8. IF the uploaded file fails magic-byte verification for PDF format, THEN THE Parser SHALL reject the upload and return an error response indicating the file is not a valid PDF
9. IF parsing exceeds the configurable wall-clock timeout (default: 120 seconds), THEN THE Parser SHALL terminate the operation and return a timeout error
10. IF the PDF contains nesting depth exceeding 20 levels or individual pages exceeding 50 megabytes of raw content, THEN THE Parser SHALL fail closed and return an error indicating pathological input rather than produce corrupted output
11. WHEN a valid PDF document is parsed into markdown and that markdown is re-parsed, THE Parser SHALL produce a document tree with the same node count, the same heading hierarchy, and the same content ordering as the original parse result

#### Correctness Properties

- **CP-2.1 (Round-Trip)**: For all valid PDF documents, parse(document) → markdown → re-parse SHALL produce a structurally equivalent document tree (same node count, heading hierarchy, content ordering)
- **CP-2.2 (Reconciliation Completeness)**: For any parsed document, the sum of mapped blocks plus explicitly unmapped blocks SHALL equal the total extracted blocks — zero blocks vanish unexplained
- **CP-2.3 (Determinism)**: For any valid PDF, parsing the same file N times SHALL produce byte-identical markdown output

### Requirement 3: Document Tree Construction

**User Story:** As a QA engineer, I want parsed content converted into a validated hierarchical tree, so that document structure is accurately represented for selection and generation.

#### Acceptance Criteria

1. WHEN parsed content is provided, THE Tree_Engine SHALL produce a hierarchical tree where each Document_Node contains heading, body, depth (ranging from 0 for root to a maximum of 10), parent reference, children list, parsed number, order index, lineage_id placeholder, and Content_Hash
2. WHEN the parsed content contains duplicate headings, THE Tree_Engine SHALL disambiguate nodes by assigning each a unique combination of parent lineage and sibling order index such that no two nodes in the tree share the same (parent reference, heading, order index) tuple
3. WHEN the parsed content contains skipped heading levels (e.g., heading level jumps from 2 to 4), THE Tree_Engine SHALL insert the node as a child of the nearest ancestor whose depth is less than the node's heading level
4. WHEN the parsed content contains out-of-order numbering, THE Tree_Engine SHALL preserve the document's original ordering by assigning order indices based on source-document sequence rather than parsed number values
5. WHEN the parsed content contains numbered-list items that resemble headings, THE Tree_Engine SHALL classify the items as list content within the parent node's body rather than creating separate Document_Nodes
6. WHEN the parsed content contains tables spanning multiple pages, THE Tree_Engine SHALL reconstruct the table as a single coherent node attached to the heading that immediately precedes the table's first occurrence
7. THE Tree_Engine SHALL validate that every node (except the root) has exactly one parent
8. THE Tree_Engine SHALL validate that no cycles exist in the tree
9. THE Tree_Engine SHALL validate that node depth values equal parent depth plus one for every non-root node
10. THE Tree_Engine SHALL validate that sibling order indices form a contiguous zero-based sequence within each parent
11. IF any tree validation check (single parent, cycle detection, depth consistency, or sibling order) fails, THEN THE Tree_Engine SHALL reject the tree, return an error response indicating which validation rule failed and the offending node identifier, and SHALL NOT persist the invalid tree
12. WHEN tree construction completes successfully, THE Tree_Engine SHALL compute a Content_Hash for each node using the concatenation of the node's heading and body content, such that identical content always produces the same hash value

#### Correctness Properties

- **CP-3.1 (Tree Integrity)**: For all constructed trees, every non-root node has exactly one parent, no cycles exist, depth equals parent depth plus one, and sibling indices are contiguous zero-based
- **CP-3.2 (Hash Determinism)**: For any two nodes with identical heading and body content, their Content_Hash values SHALL be equal
- **CP-3.3 (Ordering Preservation)**: For all input documents, the pre-order traversal of the constructed tree SHALL reflect the original document ordering

### Requirement 4: Data Persistence

**User Story:** As a developer, I want document data persisted in a normalized schema with integrity guarantees, so that versions and nodes are stored reliably and idempotently.

#### Acceptance Criteria

1. THE Persistence_Layer SHALL store data in a normalized SQLite schema with tables for documents, versions, nodes, and selections, with foreign key enforcement enabled on every database connection
2. THE Persistence_Layer SHALL configure SQLite in WAL mode with FTS5 enabled
3. WHEN the same content (identified by Content_Hash) is ingested a second time, THE Persistence_Layer SHALL skip creating a duplicate version and return the existing version reference
4. WHEN a document tree is persisted and then reloaded, THE Persistence_Layer SHALL produce a tree with identical topology, node content, sibling ordering, depth values, and Content_Hash values as the original tree
5. IF a persistence operation fails due to a constraint violation or storage error, THEN THE Persistence_Layer SHALL roll back the entire transaction atomically, preserve any previously committed data unchanged, and return an error response indicating the failure reason
6. WHEN a document version is ingested, THE Persistence_Layer SHALL persist all nodes within a single database transaction so that either all nodes are committed or none are

#### Correctness Properties

- **CP-4.1 (Round-Trip Fidelity)**: For all document trees, persist(tree) → reload SHALL produce a structurally equal tree (identical topology, content, ordering, depth, hashes)
- **CP-4.2 (Idempotency)**: For any document with content hash H, ingesting H twice SHALL result in exactly one version record in the database
- **CP-4.3 (Atomicity)**: For any failed persistence operation, the database state SHALL be identical to the state before the operation began

### Requirement 5: Document Versioning

**User Story:** As a QA engineer, I want the system to track document changes across versions with lineage matching, so that I can understand how sections evolve and when matches are uncertain.

#### Acceptance Criteria

1. WHEN a new document version is ingested, THE Versioning_Engine SHALL attempt lineage matching using a three-tier strategy: exact Content_Hash match first, then parent-lineage plus heading match, then positional fallback
2. WHEN a lineage match is determined, THE Versioning_Engine SHALL store the match strategy used and a numeric Confidence_Score between 0.0 and 1.0
3. IF a lineage match Confidence_Score falls below the configurable threshold (default 0.75), THEN THE Versioning_Engine SHALL assign needs_review status to the match and never silently auto-accept the match
4. WHEN a new version is created, THE Versioning_Engine SHALL preserve the previous version in full without mutation
5. WHEN a diff is requested between two versions, THE Versioning_Engine SHALL return a list of added, removed, and modified nodes with their Lineage_IDs and the specific fields that changed
6. WHEN a node in the new version cannot be matched to any node in the previous version, THE Versioning_Engine SHALL classify the node as added with no lineage predecessor
7. WHEN a node in the previous version has no match in the new version, THE Versioning_Engine SHALL classify the node as removed

#### Correctness Properties

- **CP-5.1 (Strategy Ordering)**: The Versioning_Engine SHALL always attempt exact hash match before heading match, and heading match before positional fallback — no strategy is skipped
- **CP-5.2 (Confidence Threshold)**: For all matches with Confidence_Score < threshold, the match status SHALL be needs_review — never auto-accepted
- **CP-5.3 (Immutability)**: For all previous versions, no field SHALL be mutated after a new version is created
- **CP-5.4 (Determinism)**: For the same pair of document versions, lineage matching SHALL produce identical results across repeated runs

### Requirement 6: Browse and Search

**User Story:** As a QA engineer, I want to browse the document tree and search content by keywords, so that I can locate relevant sections for test case generation.

#### Acceptance Criteria

1. THE Search_Service SHALL provide endpoints for browsing the document tree hierarchy, returning nodes with their heading, depth, order index, Content_Hash, and child count, scoped to a specified document version
2. THE Search_Service SHALL provide an endpoint for retrieving a single Document_Node by identifier, returning heading, body, depth, parent reference, children list, Content_Hash, and Lineage_ID
3. IF a requested Document_Node identifier does not exist, THEN THE Search_Service SHALL return an error response indicating the node was not found
4. WHEN a full-text search query is submitted, THE Search_Service SHALL perform FTS5-based full-text search across node heading and body content within a specified document version and return matching nodes ranked by relevance
5. IF a search query is empty or shorter than 2 characters, THEN THE Search_Service SHALL return an error response indicating the query is too short
6. THE Search_Service SHALL support paginated responses for browse and search results with a default page size of 20 and a maximum page size of 100
7. THE Search_Service SHALL include document version identifier, node count, Content_Hash values, and per-request latency in milliseconds in all responses
8. WHEN content has changed between versions, THE Search_Service SHALL expose change detection information for affected nodes including the previous Content_Hash, current Content_Hash, and change type (added, modified, or removed)

#### Correctness Properties

- **CP-6.1 (Pagination Consistency)**: For any paginated query, iterating all pages SHALL return every matching node exactly once with no duplicates or omissions
- **CP-6.2 (Search Relevance)**: For any FTS5 query matching at least one node, the response SHALL contain that node in the results
- **CP-6.3 (Version Scoping)**: Browse and search results SHALL only include nodes belonging to the specified document version

### Requirement 7: Selection and QA Generation

**User Story:** As a QA engineer, I want to select document nodes and generate QA test cases from them, so that I can produce traceable, structured test cases tied to specific document content.

#### Acceptance Criteria

1. WHEN a user creates a selection referencing at least one valid Document_Node belonging to the specified document version, THE Selection_Service SHALL create an immutable, version-pinned selection referencing the specific document version and selected nodes
2. IF a selection creation request references zero nodes or references node identifiers that do not exist in the specified document version, THEN THE Selection_Service SHALL reject the request with an error response indicating the validation failure
3. WHEN a generation is requested, THE Generation_Service SHALL send a structured prompt to NVIDIA NIM (GLM-5.2) separating instructions from document content to maintain prompt-injection hygiene
4. WHEN a generation is requested, THE Generation_Service SHALL request strict JSON output from the model and validate the response against a Pydantic schema
5. WHEN generation succeeds schema validation, THE Generation_Service SHALL create a Generation_Record with status completed, the validated QA test cases, source-hashes of all selected nodes, and the selection reference for traceability
6. IF the first generation attempt fails schema validation, THEN THE Generation_Service SHALL retry exactly once
7. IF both generation attempts fail schema validation, THEN THE Generation_Service SHALL create a terminal generation_failed Generation_Record including the validation errors and never silently drop the failure
8. IF the NVIDIA NIM service is unreachable or the request exceeds the configured hard timeout (60 seconds), THEN THE Generation_Service SHALL create a terminal generation_failed Generation_Record indicating the network or timeout failure
9. THE Generation_Service SHALL enforce a default rate limit of 40 requests per minute against NVIDIA NIM, configurable via environment variable
10. THE Generation_Service SHALL record input and output token counts as reported by the NVIDIA NIM response for each generation call in the Generation_Record
11. THE Rate_Limiter SHALL enforce configurable per-client rate limits on the generation endpoint with a default of 10 requests per minute per client

#### Correctness Properties

- **CP-7.1 (Selection Immutability)**: For any persisted selection, mutating the node references or version reference SHALL be rejected — selections are write-once
- **CP-7.2 (No Silent Drops)**: For all generation attempts, exactly one Generation_Record SHALL be persisted — either completed or generation_failed — no attempt ends without a record
- **CP-7.3 (Rate Compliance)**: The Generation_Service SHALL never exceed the configured NIM rate limit across any sliding 60-second window
- **CP-7.4 (Prompt Separation)**: The prompt template SHALL structurally separate system instructions from document content such that document content cannot alter the system instruction section

### Requirement 8: Impact Analysis

**User Story:** As a QA engineer, I want to know when generated test cases are stale due to documentation changes, so that I can re-generate test cases for updated content.

#### Acceptance Criteria

1. WHEN impact analysis is requested for a Generation_Record, THE Impact_Analyzer SHALL compare each source-hash stored in that Generation_Record against the Content_Hash of the corresponding node (matched by Lineage_ID) in the latest version of the same document
2. IF all source-hashes match the latest lineage hashes, THEN THE Impact_Analyzer SHALL return a current status with no changed nodes
3. IF one or more source-hashes differ from the latest lineage hashes, THEN THE Impact_Analyzer SHALL return the stale status, the list of changed node Lineage_IDs, a diff summary identifying which fields changed per node, and a staleness reason per node indicating whether the change is a direct content change or a descendant content change
4. IF a source node's Lineage_ID has no corresponding node in the latest document version, THEN THE Impact_Analyzer SHALL report that node as missing and include it in the stale response with a reason indicating the node was removed or unmatched
5. WHEN a generation is stale, THE Impact_Analyzer SHALL classify each changed node as either a direct node content change or a descendant node content change based on whether the node itself or only its children have different Content_Hashes
6. THE Impact_Analyzer SHALL treat staleness as a computed view and never mutate historical Generation_Records

#### Correctness Properties

- **CP-8.1 (Immutability)**: For all staleness checks, the Generation_Record's stored source-hashes SHALL remain byte-identical before and after the check
- **CP-8.2 (Completeness)**: For any stale generation, every changed or missing node SHALL be reported — no stale node is omitted from the response
- **CP-8.3 (Correctness)**: IF all source-hashes match current lineage hashes, THEN the status SHALL be current; IF any differ, the status SHALL be stale

### Requirement 9: Performance and Testing

**User Story:** As a developer, I want comprehensive test coverage and performance benchmarks, so that regressions are caught early and latency targets are enforced in CI.

#### Acceptance Criteria

1. THE System SHALL maintain a test suite of at least 80 test cases with a minimum of 30 unit tests, 20 integration tests, and 10 hardening tests
2. WHEN parsing a 10-page PDF document, THE Parser SHALL complete within 2 seconds at the 95th percentile measured over a minimum of 20 consecutive runs
3. WHEN retrieving a single Document_Node, THE Persistence_Layer SHALL respond within 100 milliseconds at the 95th percentile
4. WHEN executing a full-text search query against an index containing at least 500 nodes, THE Search_Service SHALL respond within 300 milliseconds at the 95th percentile
5. WHEN generating QA test cases, THE Generation_Service SHALL complete within 15 seconds at the 95th percentile
6. IF a generation request exceeds 60 seconds of wall-clock time, THEN THE Generation_Service SHALL terminate the request and record a generation_failed Generation_Record
7. WHEN ingesting a full CT200 document of 180 to 220 pages, THE System SHALL complete the full ingest pipeline within 30 seconds
8. IF any CI benchmark run exceeds the latency thresholds defined in criteria 2 through 5 and 7, THEN THE System SHALL fail the build and report which threshold was violated

#### Correctness Properties

- **CP-9.1 (Regression Gate)**: For all CI benchmark runs, exceeding any defined latency threshold SHALL fail the build — no silent regression
- **CP-9.2 (Test Coverage)**: The test suite SHALL maintain the minimum category counts (30 unit, 20 integration, 10 hardening) — dropping below fails CI

### Requirement 10: Production Readiness and Documentation

**User Story:** As a developer or operator, I want comprehensive documentation and operational artifacts, so that the system can be deployed, maintained, and understood by the team.

#### Acceptance Criteria

1. THE System SHALL include a README containing at minimum: prerequisites and dependency versions, environment variable configuration, build and run commands, and instructions to execute the test suite
2. THE System SHALL include an APPROACH.md explaining architectural decisions and at least 2 Architecture Decision Records documenting trade-offs including technology choices and external service integrations
3. THE System SHALL include architecture diagrams in a text-based format (such as Mermaid or PlantUML) showing component relationships and request flow
4. THE System SHALL auto-generate OpenAPI documentation from the FastAPI route definitions so that the documented endpoints always reflect the implemented API
5. THE System SHALL include a known-limitations document describing current constraints and boundaries
6. THE System SHALL include a Dockerfile that builds successfully and produces a container capable of starting the application and responding to the /health endpoint
7. THE System SHALL document in an ADR that CT200 content is sent to NVIDIA NIM for generation, including the rationale, data-flow description, and privacy considerations
8. THE System SHALL provide a /docs endpoint serving Swagger UI interactive API documentation that is accessible without authentication

#### Correctness Properties

- **CP-10.1 (Docker Bootability)**: Building the Dockerfile and running the container SHALL result in a process responding to GET /health with HTTP 200
- **CP-10.2 (API Docs Accuracy)**: The OpenAPI spec served at /docs SHALL reflect all implemented endpoints with their actual request/response schemas

### Requirement 11: Observability

**User Story:** As an operator, I want structured observability across the system, so that I can monitor health, debug issues, and track performance in production.

#### Acceptance Criteria

1. THE System SHALL produce structured JSON logs for all operations at INFO level and above, where each log entry contains at minimum: timestamp, log level, Correlation_ID, logger name, and message
2. THE System SHALL attach a unique Correlation_ID to every log entry within a single request lifecycle
3. THE System SHALL never log document node body text or raw PDF binary content at INFO level or below
4. THE Health_Controller SHALL expose Prometheus-format metrics that include, at minimum, per-endpoint request counts, per-endpoint response latency histograms, and per-endpoint error counts
5. WHILE the database connection is unavailable, THE Health_Controller SHALL return HTTP 503 from the /ready endpoint within 5 seconds of receiving the readiness check request

#### Correctness Properties

- **CP-11.1 (Correlation Consistency)**: For any single request, all log entries SHALL carry the same Correlation_ID value
- **CP-11.2 (No Content Leakage)**: At INFO level and below, no log entry SHALL contain raw document content or PDF binary data
- **CP-11.3 (Readiness Accuracy)**: The /ready endpoint SHALL return 503 if and only if the database is unreachable

### Requirement 12: Security

**User Story:** As a security engineer, I want the system hardened against common attack vectors, so that unauthorized access, injection attacks, and supply chain risks are mitigated.

#### Acceptance Criteria

1. IF a request lacks valid authentication credentials, THEN THE Auth_Guard SHALL reject the request with HTTP 401 on all endpoints except /health, /ready, and /metrics
2. THE Rate_Limiter SHALL enforce configurable per-client rate limits on ingestion and generation endpoints with a default of 60 requests per minute per client
3. IF a client exceeds the configured rate limit, THEN THE Rate_Limiter SHALL reject subsequent requests with HTTP 429 and include a Retry-After header indicating the number of seconds until the limit resets
4. WHEN a file is uploaded, THE Parser SHALL verify the file does not exceed 50 megabytes, passes magic-byte verification for PDF format, and completes within a configurable wall-clock timeout (default 120 seconds)
5. THE System SHALL load all secrets and credentials exclusively from environment variables with no secrets committed to source control
6. THE Generation_Service SHALL use a structured prompt template that separates system instructions from user-provided document content to mitigate prompt-injection attacks
7. THE System SHALL run pip-audit in CI and fail the build if any known vulnerability with severity high or critical is detected in dependencies

#### Correctness Properties

- **CP-12.1 (Auth Enforcement)**: For all non-exempt endpoints, a request without valid credentials SHALL receive HTTP 401 — never a successful response
- **CP-12.2 (Rate Limit Enforcement)**: For any client exceeding the rate limit, the next request within the window SHALL receive HTTP 429
- **CP-12.3 (No Secret Leakage)**: No file tracked in source control SHALL contain API keys, tokens, or credentials
