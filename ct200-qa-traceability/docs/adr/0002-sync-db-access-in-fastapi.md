# ADR 0002: Synchronous database access in FastAPI

## Status
Accepted

## Context
FastAPI supports both async and sync route handlers. The application uses SQLAlchemy's synchronous session API with SQLite, which does not benefit from async I/O. The only async operation is PDF parsing via PyMuPDF (CPU-bound, run in a thread).

## Decision
Use synchronous SQLAlchemy sessions. FastAPI automatically runs sync route handlers in a thread pool, preventing event-loop blocking for the database-touching endpoints.

## Consequences
- No async/await ceremony around database queries — simpler, more readable code.
- FastAPI's thread pool handles concurrency for sync routes transparently.
- If the application migrates to PostgreSQL with asyncpg, routes would need to become async and use AsyncSession — a bounded, well-understood migration.
- The PDF parser remains async (uses asyncio.to_thread internally) and is called with await in the one async route that handles file upload.
