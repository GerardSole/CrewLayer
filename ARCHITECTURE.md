# Architecture

## Overview

CrewLayer is a stateless FastAPI application backed by PostgreSQL (via pgvector) and Redis. All persistent state lives in Postgres; Redis handles short-term session memory, embedding caches, and pub/sub for real-time SSE streams.

```
  landing/ (Vercel)   docs/ (Vercel)

Electron Desktop App (desktop/)
  ├── PostgreSQL (embedded)
  ├── Redis (embedded)
  └── FastAPI + Dashboard (embedded)    ← self-contained; same API surface as below

Claude Desktop / Claude Code
        │ stdio or SSE
        ▼
   MCP Server (mcp/server.py)         Prometheus ◄── /metrics (token-auth)
        │ HTTP internal                   │
        ▼                             Grafana dashboard
Python SDK (sdk/)  TypeScript SDK (sdk-typescript/)  CLI (crewlayer cli)
        │                    │                │
        └────────────────────┴────────────────┘
                             │ HTTP (X-API-Key)       Dashboard (React/Vite)
                             │                              │ /dashboard/
                             └──────────────────────────────┘
                             │ HTTP (X-API-Key / JWT)
                             ▼
                       FastAPI (async)
                             │
        ┌────────────────────┴────────────────────────────────────────┐
        │  API Layer  (crewlayer/api/)                                │
        │  ┌────────┬──────────┬──────────┬────────┬─────────────┐   │
        │  │  auth  │  agents  │  memory  │actions │   context   │   │
        │  │  audit │ sessions │ webhooks │ usage  │   metrics   │   │
        │  │prompts │ episodes │          │ alerts │ evaluations │   │
        │  └────┬───┴────┬─────┴─────┬────┴───┬────┴────┬────────┘   │
        └───────┼────────┼───────────┼────────┼─────────┼────────────┘
                │        │           │        │         │
           ┌────▼──┐  ┌──▼───┐  ┌───▼────┐ ┌─▼───┐  ┌─▼──────────┐
           │Audit  │  │ ORM  │  │ Memory │ │Actn │  │Context     │
           │Middle-│  │Models│  │ Engine │ │Logr │  │Broker      │
           │ ware  │  │      │  │(short/ │ │     │  │(pub/sub    │
           └───────┘  └──┬───┘  │long/   │ │     │  │→ SSE)      │
                         │      │ decay/ │ │     │  │+ History   │
                   ┌─────▼──┐   │episod.)│ └─────┘  └───┬────────┘
                   │Postgres│◄──┘    │                   │
                   │+pgvec  │        │            ┌──────▼──┐
                   └────────┘   ┌────▼────┐       │  Redis  │
                                │Portabil.│       │(pub/sub)│
                                │export / │       └─────────┘
                                │ import  │
                                └─────────┘
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
| `memory/long.py` | PostgreSQL rows with a `vector(1536)` column. Recall uses `cosine_distance` via pgvector. Soft-delete via `deleted_at`. Excludes archived memories from recall. |
| `memory/extractor.py` | Calls `claude-opus-4-8` to extract structured facts from a conversation string and persists them via `LongMemory`. |
| `memory/merger.py` | Near-duplicate detection (cosine similarity ≥ 0.90). Calls Claude to merge both texts; soft-deletes the original; the merged row stores `merged_from=[original.id]`. |
| `memory/decay.py` | Automatic forgetting, running daily at 03:00 UTC. Three rules per tenant (see below). |
| `embeddings/client.py` | Single entry point for embedding generation. Supports Voyage AI (via Anthropic API key) and local sentence-transformers. Results cached in Redis (TTL 24h). |

##### Automatic forgetting rules (`memory/decay.py`)

Rules are applied in priority order (1 → 3 → 2) so a memory matching multiple rules is handled by the most severe one only.

| Rule | Condition | Action |
|---|---|---|
| 1 — Hard delete | `importance < forget_threshold` AND `last_accessed < now − delete_after_days` | Physically removed from DB |
| 3 — Archive | `importance < 0.15` AND `last_accessed < now − archive_after_days` | `status = "archived"`, excluded from recall |
| 2 — Decay | `access_count == 0` AND `created_at < now − 14 days` | `importance *= 0.80` (floor: 0.01) |

Per-tenant config lives in `Tenant.settings` (JSON): `memory_decay_enabled`, `memory_forget_threshold` (default 0.05), `memory_archive_after_days` (default 60), `memory_delete_after_days` (default 30).

#### Action logger (`actions/logger.py`)

Append-only store. Supports:
- Cursor-based pagination: cursor = `base64(f"{timestamp.isoformat()}|{id}")`, keyset on `(timestamp DESC, id DESC)`
- Aggregate stats: total, error rate, avg duration, breakdown by tool name

#### Blackboard (`context/blackboard.py`)

Shared namespace-scoped key/value store for multi-agent coordination.
- Optimistic locking: `expected_version=0` asserts the key is new; `expected_version=N` asserts the current version. Mismatch → `VersionConflictError` → HTTP 409.
- Expiry: entries with a past `expires_at` are invisible to reads and excluded from namespace listings.
- Background cleanup: `main.py` runs `cleanup_expired()` in a loop every 60 s.

#### Pub/Sub in Blackboard (`core/streaming/context_broker.py`)

Every write to `PUT /v1/context/{namespace}/{key}` publishes a JSON message to Redis channel `context:{tenant_id}:{namespace}:{key}`. Clients subscribe via `GET /v1/context/{namespace}/{key}/subscribe` (SSE).

```
HTTP PUT /v1/context/ns/key
  │
  ├── Write to Postgres (blackboard table)
  └── redis.publish("context:{tid}:{ns}:{key}", json_payload)
                          │
                          ▼
              ContextBroker (asyncio.Queue per subscriber)
                          │
                          ▼
              GET /v1/context/ns/key/subscribe  ← SSE stream
              (EventSourceResponse, heartbeat every 30 s,
               1 s disconnect-poll, 1 h max duration)
```

The broker uses a **dedicated Redis connection** (separate from the shared pool) to avoid pubsub pool contention. The `main.py` lifespan manages its lifecycle.

#### Audit log (`api/middleware/audit.py`)

Pure ASGI middleware that fires **after** authentication and **after** the response is sent. Captures `POST`, `PUT`, `PATCH`, `DELETE` requests. Each entry is immutable (no update/delete endpoints). Stored in the `audit_log` table and exposed read-only via `GET /v1/audit-log` (cursor-paginated).

#### Agent status (`agents/`)

`Agent` has three new fields: `status` (idle/working/error), `status_updated_at`, `current_session_id`. Status is cached in Redis (`agent_status:{id}`, TTL 60 s) for fast reads. Session lifecycle transitions update the status automatically.

#### Agent tags (`agents/`)

`tags TEXT[]` column on `agents` with a GIN index. `GET /v1/agents?tags=a,b` uses the `@>` (contains) operator. `GET /v1/agents/tags` returns `[{tag, count}]`. Tag mutations (`POST /{id}/tags`, `DELETE /{id}/tags/{tag}`) add/remove without overwriting the full array.

#### Agent alerts (`actions/alerts.py`)

After each action commit, `check_and_fire_alerts()` is called. Redis key `alert:{tenant}:{agent}:consecutive_errors` tracks consecutive failures (INCR on error, SET 0 on success). Fires `agent.alert` webhook when the count reaches `alert_on_consecutive_errors` (default 5). Also checks error rate over the last 20 actions against `alert_on_error_rate_percent` (default 80 %).

#### Episodic memory (`core/memory/episodic.py`)

Episodes group long-term memories under named task boundaries that may span multiple sessions.

```
Episode (title, status: active/completed/archived)
  └── Session (episode_id FK, nullable)
       └── Memories (linked via EpisodeMemory join table)
```

`EpisodicMemory.add_session_to_episode()` sets `Session.episode_id` and back-fills the `episode_memories` link table by finding all memories created within the session's time window. `complete_episode()` calls `claude-opus-4-8` to generate a narrative summary from all linked sessions and memories. `recall_episode()` scopes a pgvector cosine search to a single episode's memories.

#### Agent hierarchy and relations (`core/agents/relations.py`)

Three relation types, each directional:

```
supervisor ──► subordinate   (one per subordinate; no cycles)
agentA ◄─────► agentB        (collaborator; bidirectional pair)
delegator ───► delegate       (lightweight; many allowed)
```

Validation rules enforced in `AgentRelations.set_relation()`:
- Self-relation → `SelfRelationError`
- Cycle detection via BFS → `CycleError`
- Multiple supervisors for the same agent → `DuplicateSupervisorError`

**Blackboard propagation**: `PUT /v1/context/{ns}/{key}` with `propagate=true` and `written_by=agent_id` automatically writes the same key/value to every subordinate agent's namespace (their ID as namespace), after the main write commits.

#### Context history (`context/blackboard.py`)

Every `write()` and `delete()` appends an immutable `ContextHistory` row in the same transaction. Three read-only endpoints:
- `GET /v1/context/{ns}/{key}/history` — cursor-paginated, newest first
- `GET /v1/context/{ns}/{key}/history/{version}` — point-in-time value
- `POST /v1/context/{ns}/{key}/rollback` — restore a prior version (creates a `rollback` history entry)

Re-creating a deleted key continues the version sequence using `MAX(history.version) + 1`.

#### Agent portability (`core/agents/portability.py`)

Export/import as a self-contained JSON snapshot.

**Export flow** (`GET /v1/agents/{id}/export`):
1. `stream_export_agent()` yields the header, then each resource section using `db.stream_scalars()` server-side cursors (avoids loading all embeddings into memory).
2. Actions are limited to the last 90 days.
3. Embeddings are serialised as `[float(x) for x in mem.embedding]` — pgvector returns `numpy.float32` which is not JSON-serialisable directly.
4. Returns a `StreamingResponse` with `Content-Disposition: attachment`.

**Import flow** (`POST /v1/agents/import`):
1. `AgentExportData` Pydantic model validates the payload (rejects unsupported `export_version`).
2. `async with db.begin_nested()` creates a PostgreSQL savepoint — any failure rolls back cleanly without aborting the outer transaction.
3. Insert order: Agent → Episodes → Sessions → Memories → Actions → EpisodeMemories.
4. Returns an `id_map` (old UUID → new UUID) for every resource type.
5. `asyncio.create_task(regenerate_embeddings_background(new_memory_ids))` re-embeds all memories in background using a separate `AsyncSessionLocal()` — the import response is returned immediately.

#### Evaluation layer (`core/evaluation/`)

Tables: `evaluations`, `anomalies`, `ab_tests`, `ab_test_assignments`.

**Evaluations** (`evaluations`): Human ratings attached to actions — thumbs up/down and/or a numeric 1–5 score. Optional `prompt_version_id` FK enables per-version quality tracking.

**Anomaly detection** (`anomalies`): `AnomalyManager` is called after action writes. Detects:
- `latency_spike` — action duration ≥ 3× the agent's rolling average
- `error_burst` — ≥ 5 consecutive errors (reuses the Redis counter from `actions/alerts.py`)
- `evaluation_drop` — rolling avg score drops below a tenant-configured threshold

Detected anomalies fire `agent.anomaly` webhooks and are surfaced in the Evaluations dashboard page.

**A/B testing** (`ab_tests`, `ab_test_assignments`): Compare two `PromptVersion` variants. Sessions are assigned to variant A or B based on `traffic_split` (default 0.5). `GET .../ab-tests/{id}/results` returns comparative metrics per variant (avg score, thumbs ratio, error rate). `POST .../ab-tests/{id}/complete` declares a winner and optionally activates the winning prompt version.

```
Action logged (POST /v1/agents/{id}/actions)
  │
  ├── AnomalyManager.check_after_action()
  │     └── detect latency_spike / error_burst → insert anomaly row
  │
  └── ABTestManager.get_assignment()   ← if an active A/B test exists for this agent
        └── assign session to variant A or B → record in ab_test_assignments
```

#### Prompt management (`core/prompts/`)

Table: `prompt_versions`.

Each agent can have multiple `PromptVersion` rows, auto-incremented by version number. At most one version has `is_active=True`; `PromptManager.activate()` atomically deactivates the current one. `actions.prompt_version_id` (nullable FK) links every logged action to the prompt that was active when it ran, enabling per-version quality metrics in evaluations and A/B tests.

`GET /v1/agents/{id}/prompts/diff?a=<id>&b=<id>` returns a line-by-line unified diff. `POST .../rollback` activates the version immediately before the current active one.

### Database (`crewlayer/db/`)

Nine tables:

```
tenants
  └── api_keys            (FK → tenants; scopes text[]; agent_ids uuid[]; bcrypt hash)
  └── agents              (status enum; status_updated_at; current_session_id; tags text[])
       └── sessions        (FK → agents; episode_id FK nullable; status enum; started_at/closed_at)
       └── memories        (vector(1536); base_importance; merged_from uuid[];
                            status enum active/archived; soft-delete via deleted_at)
       └── actions         (immutable append-only; prompt_version_id FK nullable → prompt_versions)
       └── episodes        (title; status enum active/completed/archived; summary; started_at/completed_at)
       └── prompt_versions (version int auto-increment; content text; is_active bool;
                            description; created_by FK → api_keys)
       └── evaluations     (action_id FK; rating_thumbs enum up/down; rating_score 1–5;
                            prompt_version_id FK nullable; notes; created_by FK → api_keys)
       └── anomalies       (anomaly_type enum; severity enum; resolved bool; metadata jsonb)
       └── ab_tests        (name; variant_a/b_prompt_version_id FK; traffic_split float;
                            status enum; winner enum nullable)
       └── ab_test_assignments (ab_test_id FK; session_id FK; variant enum A/B;
                                unique on ab_test_id + session_id)
       └── agent_status_history (agent_id FK; old_status enum; new_status enum;
                                 changed_at TIMESTAMPTZ; source text)
  └── episode_memories    (composite PK: episode_id + memory_id; join table)
  └── agent_relations     (supervisor_id, subordinate_id, relation_type enum; unique per pair)
  └── context_entries     (unique on tenant+namespace+key; expires_at; written_by)
  └── context_history     (immutable; namespace, key, value, version, operation enum, created_at)
  └── webhooks            (url, events[], secret_hash)
  └── audit_log           (immutable; tenant_id, api_key_id, method, path,
                           status_code, request_body, response_body, created_at)
```

All tables use `UUID` primary keys (`uuid4`). All timestamps are `TIMESTAMPTZ`.

Migrations: Alembic with async engine (`NullPool` during migration to avoid pool leak). Current head: `f2a3b4c5d6e7`.

Key enum types:
- `agent_status_enum` (idle/working/error)
- `memory_status_enum` (active/archived)
- `session_status` (active/closed)
- `episode_status_enum` (active/completed/archived)
- `agent_relation_type_enum` (supervisor/collaborator/delegate)
- `context_operation_enum` (created/updated/deleted/rollback)
- `rating_thumbs_enum` (up/down)
- `anomaly_type_enum` (latency_spike/error_burst/evaluation_drop)
- `anomaly_severity_enum` (low/medium/high/critical)
- `ab_test_status_enum` (active/completed/cancelled)
- `ab_test_variant_enum` (A/B)
- `ab_test_winner_enum` (A/B/inconclusive)

### Security

- **API key format**: `crwl_{uuid32hex}_{urlsafe_secret}` — the UUID segment is the row's primary key, enabling direct DB lookup without scanning all keys.
- **Hashing**: `bcrypt` (direct, not passlib) with default rounds.
- **Tenant isolation**: every query filters by `tenant_id`. Foreign resource access returns 404, never 403.
- **Granular scopes**: `api_keys.scopes` is a text array. Values: `memory:read`, `memory:write`, `actions:read`, `actions:write`, `context:read`, `context:write`, `sessions:read`, `sessions:write`, `agents:read`, `agents:write`. Routes declare their required scope via `check_scope()` dependency; missing scope → HTTP 403.
- **Agent-restricted keys**: `api_keys.agent_ids` optionally limits a key to a specific set of agents. Access to any other agent → 403.
- **Rate limiting**: per-API-key sliding window enforced in `api/middleware/ratelimit.py` using Redis.

### MCP Server (`mcp/server.py`)

FastMCP-based server exposing 9 tools to LLM clients (Claude Desktop, Claude Code):

| Tool | Maps to |
|---|---|
| `memory_recall` | `POST /v1/agents/{id}/memory/recall` |
| `memory_append` | `POST /v1/agents/{id}/memory/messages` |
| `memory_extract` | `POST /v1/agents/{id}/memory/extract` |
| `action_log` | `POST /v1/agents/{id}/actions` |
| `action_list` | `GET /v1/agents/{id}/actions` |
| `context_write` | `PUT /v1/context/{namespace}/{key}` |
| `context_read` | `GET /v1/context/{namespace}/{key}` |
| `agent_status` | `GET /v1/agents/{id}/status` |
| `agent_set_status` | `PATCH /v1/agents/{id}/status` |

Authentication: the MCP server uses `CREWLAYER_API_KEY` to call the local REST API. Transport is controlled by `MCP_TRANSPORT`: `stdio` (Claude Desktop/Code) or `sse` (Docker, port `MCP_PORT`).

### Observability

`GET /metrics` serves Prometheus text format. Access is allowed from localhost unconditionally, or from any IP with `X-Metrics-Token: <METRICS_TOKEN>` or `Authorization: Bearer <METRICS_TOKEN>`.

Six custom Gauges refreshed every 60 s:
- `crewlayer_agents_total` — agents by status
- `crewlayer_memories_total` — memories by status (active/archived)
- `crewlayer_actions_total` — total action log entries
- `crewlayer_sessions_active` — currently active sessions
- `crewlayer_tenants_total` — total tenants
- `crewlayer_webhooks_total` — registered webhooks

`docker-compose.observability.yml` adds Prometheus (scrapes `:8000/metrics`) and Grafana (`:3000`). The pre-built dashboard JSON lives at `observability/grafana/dashboards/crewlayer.json`.

### SDKs

#### Python SDK (`sdk/`)

Installable as `pip install crewlayer` (PyPI v0.1.1) or `pip install ./sdk` from source. Provides:
- `CrewLayerClient` (sync) and `AsyncCrewLayerClient` (async) backed by `httpx`
- Retry with exponential backoff (3 retries, 1 s/2 s/4 s) on 5xx and transport errors
- Typed exceptions: `AuthError`, `NotFoundError`, `ConflictError`, `RateLimitError`, `ServerError`
- Typed response dataclasses mirroring the API schemas

#### TypeScript SDK (`sdk-typescript/`)

Installable as `npm install crewlayer` (or local `npm install ./sdk-typescript`). Provides:
- `CrewLayerClient` with sub-clients: `memory`, `actions`, `context`, `agents`, `sessions`, `episodes`
- Fetch-based transport — works in Node.js 18+ and modern browsers (no axios)
- Same retry and error hierarchy as the Python SDK
- `client.context.subscribe({ namespace, key })` → `ContextSSEStream` with `.on("updated" | "deleted" | "error" | "close", handler)` and `.close()`
- Built with tsup → ESM (`dist/index.mjs`) + CJS (`dist/index.js`) + TypeScript declarations

### Dashboard (`dashboard/`)

Web interface built with **React 18**, **React Router v6**, **TanStack Query v5**, **Recharts**, and **Radix UI / shadcn-ui** primitives. Styled with Tailwind CSS, **Outfit** typeface, and a neutral grey palette.

**Pages:**

| Page | Description |
|---|---|
| Overview | Metrics summary — active agents, error rate, memory/action counts, 7-day usage chart |
| Agents | CRUD agent list; per-agent detail view with tabs: Memory, Actions, Evaluations, Prompts |
| Memory | Long-term memories across all agents; semantic search via `POST /memory/recall` |
| Actions | Global action log with tool, status, and date filters |
| Evaluations | Thumbs/score trend charts, per-prompt-version breakdown, A/B test results |
| Prompts | Version history table, line-by-line diff viewer, activate/rollback controls |
| Blackboard | Live key/value view with SSE real-time updates |
| Webhooks | Register and manage webhook endpoints |
| Audit Log | Immutable audit trail, cursor-paginated |
| Settings | API key and tenant configuration |

`Ctrl+K` / `Cmd+K` opens the command palette for keyboard-driven navigation between pages.

**Serving in production:**

`docker compose build` runs `npm run build` inside `dashboard/` (base URL `/dashboard/`), producing `dashboard/dist/`. `main.py` serves it via:
- `GET /dashboard/assets/*` — direct static file mount
- `GET /dashboard/{path:path}` — SPA catch-all returns `index.html`

In development (`npm run dev`), Vite runs on `localhost:5173` and proxies `/v1/*` and `/health` to `localhost:8000`.

### CLI (`crewlayer/cli/`)

Installable as `pip install crewlayer[cli]` (typer + rich). Entry point: `crewlayer.cli.main:app`. Config stored at `~/.crewlayer/config.json` (chmod 0o600).

Sub-commands: `init`, `config`, `tenants create`, `keys create/list`, `agents list/create/status`, `memory recall/list`, `actions list/stats`, `export`, `import`. Every list/detail command supports `--json` for pipeline use (pipes into `jq`, CI scripts, etc.).

### Desktop App (`desktop/`)

A native Electron application that bundles the entire CrewLayer backend — PostgreSQL, Redis, and FastAPI — into a single downloadable executable. Targets macOS, Windows, and Linux.

**Startup flow:**
1. Electron main process starts embedded PostgreSQL and Redis if not already running.
2. Runs `alembic upgrade head` against the embedded database.
3. Spawns the FastAPI server on `localhost:8000`.
4. Opens a `BrowserWindow` pointing at `http://localhost:8000/dashboard`.

No Docker or external infrastructure is required. Embedded services stop when the Electron window closes. Download from [GitHub Releases](https://github.com/GerardSole/CrewLayer/releases) (tag `v0.1.0-desktop`).

### Landing & Docs

- **`landing/`** — static marketing site deployed to Vercel. Includes a `download.html` page with platform-specific download buttons linking to GitHub Releases assets.
- **`docs/`** — reference documentation site deployed to Vercel alongside the landing page.

Both are independent of the FastAPI backend and have no Python dependencies.

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
  ├── SELECT memories WHERE tenant_id=... AND status='active' ORDER BY cosine_distance(embedding, query_vec)
  └── update last_accessed + access_count + recalculate importance from base_importance for returned rows
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
| `METRICS_TOKEN` | `""` | Bearer token for `/metrics` access from non-localhost IPs |
| `MCP_PORT` | `8001` | Port for MCP server in SSE transport mode |
| `MCP_TRANSPORT` | `stdio` | `stdio` or `sse` |
| `CREWLAYER_API_KEY` | `""` | API key used by the MCP server to call the REST API |
