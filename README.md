# CT200 QA Traceability

![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-61%2F61%20Passing-success)
![Coverage](https://img.shields.io/badge/Coverage-90%25-brightgreen)
![Main.py](https://img.shields.io/badge/main.py-100%25-success)
![Ruff](https://img.shields.io/badge/Ruff-Passing-success)
![Black](https://img.shields.io/badge/Black-Formatted-success)
![MyPy](https://img.shields.io/badge/MyPy-Passing-success)

A deterministic FastAPI backend for reconstructing technical PDF manuals into **versioned semantic trees**. The system extracts document structure, preserves hierarchy, tracks lineage across revisions, and exposes a clean REST API for QA traceability workflows.

> **Status**
>
> - ✅ 61/61 automated tests passing
> - ✅ 90% overall test coverage
> - ✅ `main.py` – 100% coverage
> - ✅ `schemas.py` – 100% coverage
> - ✅ `reporting.py` – 100% coverage
> - ✅ Ruff clean
> - ✅ Black formatted
> - ✅ MyPy passing

---

## Highlights

- Layout-aware PDF parsing using PyMuPDF
- Deterministic semantic tree reconstruction
- Stable SHA-256 semantic hashing
- Versioned document persistence
- Immutable version-pinned selections
- Node lineage tracking
- SQLite + SQLAlchemy 2.x
- FastAPI + Pydantic v2
- Production-oriented testing and quality gates

## Architecture

```text
Client
   │
FastAPI
   │
Parser
   │
Semantic Tree
   │
Versioning
   │
SQLite / SQLAlchemy
```

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI |
| Database | SQLite + SQLAlchemy |
| Parsing | PyMuPDF |
| Validation | Pydantic v2 |
| Testing | pytest, pytest-cov, Hypothesis |
| Quality | Ruff, Black, MyPy |

## API

| Method | Endpoint |
|---------|----------|
| GET | /health |
| POST | /api/v1/documents |
| GET | /api/v1/documents/{id}/nodes |
| GET | /api/v1/nodes/{id}/diff |
| POST | /api/v1/selections |

## Quality Report

| Metric | Result |
|--------|--------|
| Tests | **61 / 61 Passing** |
| Overall Coverage | **90%** |
| main.py | **100%** |
| schemas.py | **100%** |
| reporting.py | **100%** |
| Ruff | ✅ |
| Black | ✅ |
| MyPy | ✅ |

## Running

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn ct200.main:app --reload
```

Run checks:

```bash
pytest
pytest --cov=src/ct200
ruff check src tests
black --check src tests
mypy src
```

## Project Structure

```text
src/
tests/
alembic/
docs/
pyproject.toml
Dockerfile
docker-compose.yml
```

## Design Principles

- Deterministic parsing
- No fabricated hierarchy
- Append-only version history
- Stable semantic hashes
- Source-order persistence
- Clean, testable architecture

## Roadmap

- Authentication & authorization
- FTS5 search endpoint
- OCR for scanned PDFs
- Docker CI validation
- Automated lineage confidence review

## License

No license has been added yet.
