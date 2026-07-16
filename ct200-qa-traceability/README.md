# CT200 QA Traceability System

Backend service that transforms CT200 technical PDF documents into a versioned, searchable document tree and generates traceable QA test cases using NVIDIA NIM (GLM-5.2).

## Prerequisites

- Python 3.12+
- SQLite 3.35+ (with FTS5 support)

## Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or .venv\Scripts\activate  # Windows

# Install dependencies
pip install -e ".[dev]"

# Copy environment configuration
cp .env.example .env
# Edit .env with your configuration values

# Run database migrations
alembic upgrade head
```

## Running

```bash
uvicorn ct200.main:app --reload
```

## Testing

```bash
pytest
```

## Linting & Formatting

```bash
ruff check src/ tests/
black src/ tests/
mypy src/
```
