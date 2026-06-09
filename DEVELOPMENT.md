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

The pub/sub and SSE-related tests (`test_context_subscribe.py`) subscribe directly to Redis channels to avoid httpx ASGI transport cleanup issues. They also require Redis to be running. The context broker in tests uses a **dedicated Redis client on DB 1** to avoid pubsub pool contention with the shared test client.

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
│   ├── middleware/      # ASGI middleware (audit log, rate limiting)
│   └── deps.py          # Shared FastAPI dependencies (auth, db, redis, check_scope)
├── core/
│   ├── memory/          # Short (Redis), long (pgvector), extractor, merger, decay
│   ├── actions/         # Action logger
│   ├── context/         # Shared blackboard
│   ├── embeddings/      # Embedding generation with Redis cache
│   ├── metrics/         # Custom Prometheus gauges (collectors.py)
│   ├── streaming/       # Pub/sub broker (broker.py, context_broker.py)
│   ├── webhooks/        # Async webhook dispatcher
│   ├── config.py        # pydantic-settings config
│   ├── redis.py         # Redis connection pool
│   └── security.py      # bcrypt helpers
├── db/
│   ├── models.py        # SQLAlchemy ORM models (all enums + tables)
│   ├── session.py       # Async session factory
│   └── alembic/versions/  # Alembic migrations (head: b8c9d0e1f2a3)
mcp/                     # MCP server (FastMCP, 9 tools)
sdk/                     # Installable Python SDK
observability/           # Grafana dashboard JSON
scripts/                 # Utility scripts (seed, etc.)
tests/                   # pytest test suite (240 tests)
docker-compose.yml                  # Main stack (Postgres + Redis)
docker-compose.observability.yml    # Prometheus + Grafana
main.py                  # FastAPI app + lifespan (background tasks)
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
| `METRICS_TOKEN` | No | Bearer token for `/metrics` from non-localhost IPs |
| `MCP_PORT` | No | MCP server SSE port. Default: 8001 |
| `MCP_TRANSPORT` | No | `stdio` (default) or `sse` |
| `CREWLAYER_API_KEY` | No | API key used by the MCP server to call the REST API |

## Observabilidad

```bash
# Levantar Prometheus + Grafana
docker compose -f docker-compose.observability.yml up -d
```

Prometheus scrapes `http://host.docker.internal:8000/metrics` every 15 s. Grafana runs on http://localhost:3000 (admin/admin).

**Importar el dashboard:**
1. Grafana → Dashboards → Import
2. Subir `observability/grafana/dashboards/crewlayer.json`
3. Seleccionar el datasource Prometheus

El dashboard muestra: total agents por status, memories activas/archivadas, action log entries, sesiones activas, latencia HTTP p50/p95/p99 por ruta.

## MCP Server

El servidor MCP expone las funciones de CrewLayer como herramientas para Claude.

### Probar con Claude Code (CLI)

Añadir al fichero de configuración MCP de Claude Code (`~/.claude/mcp_settings.json` o equivalente):

```json
{
  "mcpServers": {
    "crewlayer": {
      "command": "python",
      "args": ["-m", "mcp.server"],
      "cwd": "/ruta/a/CrewLayer",
      "env": {
        "CREWLAYER_API_KEY": "crwl_...",
        "CREWLAYER_BASE_URL": "http://localhost:8000"
      }
    }
  }
}
```

### Probar con Claude Desktop

Añadir en `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "crewlayer": {
      "command": "python",
      "args": ["-m", "mcp.server"],
      "cwd": "/ruta/a/CrewLayer",
      "env": {
        "CREWLAYER_API_KEY": "crwl_...",
        "CREWLAYER_BASE_URL": "http://localhost:8000"
      }
    }
  }
}
```

### Modo SSE (Docker)

```bash
MCP_TRANSPORT=sse MCP_PORT=8001 python -m mcp.server
```

O usando el servicio `mcp` en `docker-compose.yml`.
