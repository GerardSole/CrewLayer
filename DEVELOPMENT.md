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

CI also builds the dashboard (`npm run build` inside `dashboard/`) and verifies there are no TypeScript errors (`tsc --noEmit`). A build failure in the dashboard blocks the CI pipeline the same as a failing Python test.

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
│   ├── memory/          # Short (Redis), long (pgvector), extractor, merger, decay, episodic
│   ├── actions/         # Action logger, alert checker
│   ├── agents/          # Relations (hierarchy), portability (export/import)
│   ├── context/         # Shared blackboard + history
│   ├── embeddings/      # Embedding generation with Redis cache
│   ├── metrics/         # Custom Prometheus gauges (collectors.py)
│   ├── streaming/       # Pub/sub broker (broker.py, context_broker.py)
│   ├── webhooks/        # Async webhook dispatcher
│   ├── config.py        # pydantic-settings config
│   ├── redis.py         # Redis connection pool
│   └── security.py      # bcrypt helpers
├── cli/                 # Official CLI (typer + rich); entry: crewlayer.cli.main:app
├── db/
│   ├── models.py        # SQLAlchemy ORM models (all enums + tables)
│   ├── session.py       # Async session factory
│   └── alembic/versions/  # Alembic migrations (head: f2a3b4c5d6e7)
mcp/                     # MCP server (FastMCP, 9 tools)
sdk/                     # Installable Python SDK
sdk-typescript/          # TypeScript/JavaScript SDK (Node.js 18+ + browser)
observability/           # Grafana dashboard JSON
scripts/                 # Utility scripts (seed, etc.)
tests/                   # pytest test suite (316+ tests)
docker-compose.yml                  # Main stack (Postgres + Redis)
docker-compose.observability.yml    # Prometheus + Grafana
main.py                  # FastAPI app + lifespan (background tasks)
```

## Adding a new endpoint

1. Add the route handler in `crewlayer/api/routes/<module>.py`
2. Add Pydantic schemas in `crewlayer/api/schemas/<module>.py`
3. Put business logic in `crewlayer/core/` (not in the route)
4. Write a test in `tests/test_<module>.py`
5. Update both SDKs: `sdk/crewlayer/` (Python) and `sdk-typescript/src/resources/` (TypeScript)

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

## Observability

```bash
# Start Prometheus + Grafana + Jaeger
docker compose -f docker-compose.observability.yml up -d
```

Prometheus scrapes `http://host.docker.internal:8000/metrics` every 15 s. Grafana runs on http://localhost:3000 (admin/admin).

**Import the dashboard:**
1. Grafana → Dashboards → Import
2. Upload `observability/grafana/dashboards/crewlayer.json`
3. Select the Prometheus datasource

The dashboard shows: total agents by status, active/archived memories, action log entries, active sessions, HTTP latency p50/p95/p99 per route.

## Distributed tracing with Jaeger

CrewLayer uses OpenTelemetry to emit distributed traces. Traces are disabled by default and enabled via env var.

### Enable tracing

Add to your `.env`:

```env
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_SERVICE_NAME=crewlayer
```

Then start the observability stack (includes Jaeger):

```bash
docker compose -f docker-compose.observability.yml up -d
```

### View traces in Jaeger

Open http://localhost:16686. Select **crewlayer** from the *Service* dropdown and click **Find Traces**.

### Custom spans

The following operations produce custom spans with rich attributes:

| Span name | Attributes |
|---|---|
| `memory.recall` | `tenant_id`, `agent_id`, `query`, `top_k`, `results_count`, `embedding_cache_hit` |
| `memory.extract` | `tenant_id`, `agent_id`, `session_id`, `memories_extracted`, `model_used` |
| `memory.deduplicate` | `tenant_id`, `agent_id`, `duplicates_found`, `merges_performed` |
| `actions.log` | `tenant_id`, `agent_id`, `tool_name`, `status`, `duration_ms` |
| `context.write` | `tenant_id`, `namespace`, `key`, `version` |
| `webhooks.dispatch` | `tenant_id`, `event`, `endpoints_count`, `success_count` |

FastAPI requests, SQLAlchemy queries, and Redis commands are auto-instrumented when `OTEL_ENABLED=true`.

## MCP Server

The MCP server exposes CrewLayer functions as tools for Claude.

### Claude Code (CLI)

Add to the Claude Code MCP config (`~/.claude/mcp_settings.json` or equivalent):

```json
{
  "mcpServers": {
    "crewlayer": {
      "command": "python",
      "args": ["-m", "mcp.server"],
      "cwd": "/path/to/CrewLayer",
      "env": {
        "CREWLAYER_API_KEY": "crwl_...",
        "CREWLAYER_BASE_URL": "http://localhost:8000"
      }
    }
  }
}
```

### Claude Desktop

Add the same `mcpServers` block to `~/Library/Application Support/Claude/claude_desktop_config.json` (Mac) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows).

### SSE mode (Docker)

```bash
MCP_TRANSPORT=sse MCP_PORT=8001 python -m mcp.server
```

Or use the `mcp` service in `docker-compose.yml`.

## CLI

The official CLI lets you manage CrewLayer resources from the terminal without writing code.

### Install

```bash
# With the CLI extras (typer + rich):
pip install -e ".[cli]"

# Or from PyPI once published:
pip install crewlayer[cli]
```

### Setup wizard

```bash
crewlayer init
```

Prompts for the API base URL and your API key, tests the connection, and saves config to `~/.crewlayer/config.json`.

### Common commands

```bash
# Tenants & keys
crewlayer tenants create --name "my-project"
crewlayer keys create --name "prod" --scopes "memory:read,memory:write"
crewlayer keys list

# Agents
crewlayer agents list --status idle --tags production
crewlayer agents create --name "research-bot" --tags "research"
crewlayer agents status <agent_id>

# Memory
crewlayer memory recall <agent_id> "user preferences" --limit 5
crewlayer memory list <agent_id> --archived

# Actions
crewlayer actions list <agent_id> --status error
crewlayer actions stats <agent_id>

# Export / Import (portability)
crewlayer export <agent_id> --output agent_backup.json
crewlayer import agent_backup.json

# Pipeline / CI — every command supports --json
crewlayer agents list --json | jq '.[].id'
AGENT=$(crewlayer agents create --name "bot" --json | jq -r '.id')
```

## Dashboard

The dashboard is a React + Vite SPA located in `dashboard/`. It communicates with the backend via the REST API and is served at `/dashboard/` in production.

### Install dependencies

```bash
cd dashboard
npm install
```

### Run in development

```bash
npm run dev
```

Starts Vite on **http://localhost:5173**. The `vite.config.ts` proxy forwards `/v1/*` and `/health` to `http://localhost:8000`, so the FastAPI backend must be running (either locally or via Docker).

Login with any valid API key. The app stores credentials in `localStorage` and sends them as `X-API-Key` on every request.

**Keyboard shortcut:** `Ctrl+K` (Windows/Linux) or `Cmd+K` (macOS) opens the command palette for keyboard-driven navigation between pages.

### Production build

```bash
npm run build
# → runs: tsc && vite build --base /dashboard/
# → output: dashboard/dist/
```

The base URL `/dashboard/` ensures all asset paths and the React Router `basename` match the FastAPI mount point. After building, copy the output to the Docker volume if the backend is running in a container:

```bash
docker compose cp dashboard/dist/. api:/app/dashboard/dist/
```

The `docker compose build` command for the `api` service runs `npm run build` automatically as part of the Dockerfile, so production images always include a fresh dashboard build.

### How the dashboard is served by FastAPI

`main.py` mounts the built dashboard:

- `GET /dashboard/assets/*` — served directly as static files
- `GET /dashboard/{path:path}` — SPA catch-all returns `dashboard/dist/index.html`

Hard-refreshing any dashboard route (e.g. `/dashboard/agents`) works correctly because of this fallback.

## TypeScript SDK

The TypeScript SDK lives in `sdk-typescript/`. It targets Node.js 18+ and modern browsers (uses native `fetch`).

### Build

```bash
cd sdk-typescript
npm install
npm run build      # tsup → dist/index.mjs (ESM) + dist/index.js (CJS) + .d.ts
npm run typecheck  # tsc --noEmit
```

### Tests

```bash
npm test           # vitest run (72 tests, all mocked fetch — no server needed)
npm run test:watch # interactive watch mode
```

All tests mock `globalThis.fetch` via `vi.stubGlobal`. No running server or database required.

### Publish to npm

```bash
cd sdk-typescript
npm run build
npm publish        # publishes ./dist contents per package.json "files"
```

### Background embedding regeneration

When `POST /v1/agents/import` is called, the server returns immediately after writing all rows to the database. Embeddings are regenerated in a background task (`asyncio.create_task`) using a separate `AsyncSessionLocal()`. You can verify it is running by watching the application logs:

```
INFO  regenerating embeddings for 42 imported memories
INFO  embedding regeneration complete (42/42)
```

If the server restarts before regeneration finishes, recall results for imported memories will be incorrect until you manually trigger extraction. The `id_map` in the import response gives you the new memory IDs to check.
