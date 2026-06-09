# Development Guide

## Prerequisites

- Python 3.12+
- Docker Desktop (for PostgreSQL + Redis)
- An Anthropic API key (for embeddings and memory extraction)

## Setup

```bash
# 1. Clone and enter the project
git clone https://github.com/your-org/crewlayer
cd crewlayer

# 2. Create virtual environment and install deps
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 3. Configure environment
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY, DATABASE_URL, REDIS_URL, SECRET_KEY

# 4. Start infrastructure
docker compose up -d

# 5. Run migrations
alembic upgrade head

# 6. Start the dev server
uvicorn main:app --reload
```

Open http://localhost:8000/docs to see the interactive API docs.

## Seed demo data

```bash
python scripts/seed.py
```

Creates a demo tenant and prints an API key you can use immediately.

## Running tests

```bash
pytest tests/ -v
```

Tests require a running PostgreSQL and Redis (use `docker compose up -d`). Each test creates its own tenant and cleans up after itself. Redis uses DB 1 (production uses DB 0).

```bash
# Run a single test file
pytest tests/test_memory.py -v

# Run with coverage
pytest tests/ --cov=crewlayer --cov-report=term-missing
```

## Linting and type checking

```bash
ruff check .          # lint
ruff check . --fix    # auto-fix safe issues
mypy crewlayer/       # type check (strict mode)
```

The project uses strict mypy. All new code must pass without errors.

## Database migrations

```bash
# Auto-generate migration from model changes
alembic revision --autogenerate -m "describe the change"

# Review the generated file in alembic/versions/ before applying
alembic upgrade head

# Downgrade one step
alembic downgrade -1
```

**Important**: Always review auto-generated migrations. pgvector-specific types and custom SQL (e.g. `CREATE EXTENSION`) need to be added manually.

## Project structure

```
crewlayer/
├── api/
│   ├── routes/          # HTTP handlers (thin — no business logic here)
│   ├── schemas/         # Pydantic request/response models
│   └── deps.py          # Shared FastAPI dependencies (auth, db, redis)
├── core/
│   ├── memory/          # Short memory (Redis), long memory (pgvector), extractor
│   ├── actions/         # Action logger
│   ├── context/         # Shared blackboard
│   ├── embeddings/      # Embedding generation with Redis cache
│   ├── config.py        # pydantic-settings config
│   ├── redis.py         # Redis connection pool
│   └── security.py      # bcrypt helpers
├── db/
│   ├── models.py        # SQLAlchemy ORM models
│   ├── session.py       # Async session factory
│   └── migrations/      # Alembic versions
sdk/                     # Installable Python SDK
scripts/                 # Utility scripts (seed, etc.)
tests/                   # pytest test suite
main.py                  # FastAPI app + lifespan
```

## Adding a new endpoint

1. Add the route handler in `crewlayer/api/routes/<module>.py`
2. Add Pydantic schemas in `crewlayer/api/schemas/<module>.py`
3. Put business logic in `crewlayer/core/` (not in the route)
4. Write a test in `tests/test_<module>.py`
5. If the SDK should expose the new endpoint, update `sdk/crewlayer/`

## API versioning

All public endpoints live under `/v1/`. Breaking changes require a new version prefix (`/v2/`). The old version must continue working until explicitly deprecated.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Used for Voyage AI embeddings and Claude extraction |
| `DATABASE_URL` | Yes | `postgresql+asyncpg://user:pass@host/db` |
| `REDIS_URL` | Yes | `redis://host:6379` |
| `SECRET_KEY` | Yes | Random bytes for JWT signing |
| `EMBEDDING_PROVIDER` | No | `anthropic` (default) or `local` |
| `MAX_MEMORIES_PER_RECALL` | No | Default: 20 |
| `SHORT_MEMORY_TTL` | No | Redis TTL in seconds. Default: 3600 |
| `CONTEXT_CLEANUP_INTERVAL` | No | Background cleanup interval. Default: 60 |
