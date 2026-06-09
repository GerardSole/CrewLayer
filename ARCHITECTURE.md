# Architecture

## Overview

CrewLayer is a stateless FastAPI application backed by PostgreSQL (via pgvector) and Redis. All persistent state lives in Postgres; Redis is used only for short-term session memory and embedding caches.

```
Client / Agent SDK
       │
       ▼
  FastAPI (async)
       │
  ┌────┴──────────────────────────────────────────┐
  │  API Layer  (crewlayer/api/)                  │
  │  ┌─────────┬──────────┬──────────┬─────────┐  │
  │  │  auth   │  agents  │  memory  │ actions │  │
  │  │         │          │          │ context │  │
  │  └────┬────┴────┬─────┴─────┬────┴────┬────┘  │
  └───────┼─────────┼───────────┼─────────┼───────┘
          │         │           │         │
     ┌────▼───┐  ┌──▼───┐  ┌───▼───┐  ┌──▼───────┐
     │Security│  │ ORM  │  │Memory │  │ Action   │
     │ (bcrypt│  │Models│  │Engine │  │ Logger   │
     │  /JWT) │  │      │  │       │  │          │
     └────────┘  └──┬───┘  └───┬───┘  └──────────┘
                    │          │
              ┌─────▼──┐  ┌────▼────┐
              │Postgres│  │  Redis  │
              │+pgvec  │  │         │
              └────────┘  └─────────┘
```

## Components

### API layer (`crewlayer/api/`)

- **`routes/`** — thin HTTP handlers; no business logic. Each handler delegates to a core class.
- **`deps.py`** — FastAPI dependency injection: `TenantDep`, `DbDep`, `RedisDep`. Authentication resolves the API key to a `Tenant` on every request.
- **`schemas/`** — Pydantic v2 request/response models. Kept separate from ORM models.

### Core (`crewlayer/core/`)

#### Memory engine

| Module | Responsibility |
|---|---|
| `memory/short.py` | Redis list per session (key: `short:{tid}:{aid}:{sid}`). Capped at 200 messages, TTL refreshed on every write. |
| `memory/long.py` | PostgreSQL rows with a `vector(1536)` column. Recall uses `cosine_distance` via pgvector. Soft-delete via `deleted_at`. |
| `memory/extractor.py` | Calls `claude-opus-4-8` to extract structured facts from a conversation string and persists them via `LongMemory`. |
| `embeddings/client.py` | Single entry point for embedding generation. Supports Voyage AI (via Anthropic API key) and local sentence-transformers. Results cached in Redis (TTL 24h). |

#### Action logger (`actions/logger.py`)

Append-only store. Supports:
- Cursor-based pagination: cursor = `base64(f"{timestamp.isoformat()}|{id}")`, keyset on `(timestamp DESC, id DESC)`
- Aggregate stats: total, error rate, avg duration, breakdown by tool name

#### Blackboard (`context/blackboard.py`)

Shared namespace-scoped key/value store for multi-agent coordination.
- Optimistic locking: `expected_version=0` asserts the key is new; `expected_version=N` asserts the current version. Mismatch → `VersionConflictError` → HTTP 409.
- Expiry: entries with a past `expires_at` are invisible to reads and excluded from namespace listings.
- Background cleanup: `main.py` runs `cleanup_expired()` in a loop every 60 s.

### Database (`crewlayer/db/`)

Six tables:

```
tenants
  └── api_keys          (FK → tenants, bcrypt hash only — never raw key)
  └── agents
       └── memories     (vector(1536), soft-delete via deleted_at)
       └── actions      (immutable append-only)
  └── context_entries   (unique on tenant+namespace+key)
```

All tables use `UUID` primary keys (`uuid4`). All timestamps are `TIMESTAMPTZ`.

Migrations: Alembic with async engine (`NullPool` during migration to avoid pool leak).

### Security

- **API key format**: `crwl_{uuid32hex}_{urlsafe_secret}` — the UUID segment is the row's primary key, enabling direct DB lookup without scanning all keys.
- **Hashing**: `bcrypt` (direct, not passlib) with default rounds.
- **Tenant isolation**: every query filters by `tenant_id`. Foreign resource access returns 404, never 403.

### SDK (`sdk/`)

Installable as `pip install ./sdk`. Provides:
- `CrewLayerClient` (sync) and `AsyncCrewLayerClient` (async) backed by `httpx`
- Retry with exponential backoff (up to 4 attempts) on 5xx and transport errors
- Typed exceptions: `AuthError`, `NotFoundError`, `ConflictError`, `RateLimitError`, `ServerError`
- Typed response dataclasses mirroring the API schemas

## Data flow: memory recall

```
Agent calls POST /v1/agents/{id}/memory/recall
  │
  ▼
deps.py: validate API key → resolve Tenant
  │
  ▼
routes/memory.py: parse body (query, limit, min_similarity)
  │
  ▼
LongMemory.recall()
  ├── get_embedding(query, redis)   ← hits Redis cache first
  │     └── if miss: Voyage AI API (or local model)
  ├── SELECT memories WHERE tenant_id=... ORDER BY cosine_distance(embedding, query_vec)
  └── update last_accessed + access_count for returned rows
  │
  ▼
Return list of {memory, similarity_score}
```

## Configuration

All config in `crewlayer/core/config.py` via `pydantic-settings`. Values come from environment variables or `.env` file.

Key settings:

| Variable | Default | Description |
|---|---|---|
| `EMBEDDING_PROVIDER` | `anthropic` | `anthropic` uses Voyage AI; `local` uses sentence-transformers |
| `MAX_MEMORIES_PER_RECALL` | `20` | Upper bound on recall results |
| `SHORT_MEMORY_TTL` | `3600` | Redis TTL (seconds) for session history |
| `CONTEXT_CLEANUP_INTERVAL` | `60` | How often (seconds) the background cleanup runs |
