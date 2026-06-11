# CrewLayer

Open source backend for AI agents. Drop-in persistent memory, shared context, and full action history for any agent framework — in minutes.

```bash
git clone https://github.com/your-org/crewlayer
cd crewlayer
cp .env.example .env        # add your ANTHROPIC_API_KEY
docker compose up -d
alembic upgrade head
uvicorn main:app --reload
```

API docs: http://localhost:8000/docs

---

## What it gives you

| Feature | Details |
|---|---|
| **Short memory** | Per-session conversation history in Redis (capped list, TTL) |
| **Long memory** | Semantic recall over PostgreSQL + pgvector (cosine similarity) |
| **Memory deduplication** | Near-duplicates (cosine ≥ 0.90) are auto-merged by Claude; full lineage via `GET .../history` |
| **Automatic forgetting** | Three-rule decay system: hard-delete stale low-importance, archive cold memories, decay unaccessed ones |
| **Memory extraction** | `claude-opus-4-8` extracts facts from conversations and persists them as memories |
| **Episodic memory** | Group sessions and memories under named task episodes; Claude generates episode summaries |
| **Action log** | Immutable, append-only record of every tool call with cursor pagination and aggregate stats |
| **Agent alerts** | Configurable webhooks fired on consecutive errors or high error-rate thresholds |
| **Shared blackboard** | Namespace-scoped key/value store with optimistic locking, TTL expiry, and real-time SSE subscriptions |
| **Context history** | Immutable write log per key; point-in-time reads and one-click rollback |
| **Agent status** | idle/working/error lifecycle, Redis-cached, auto-transitions on session open/close |
| **Agent tags** | Arbitrary tags with GIN index; filter agents by tag with AND semantics |
| **Agent hierarchy** | supervisor/collaborator/delegate relations with cycle detection and blackboard propagation |
| **Agent portability** | Full JSON export/import — carry an agent across tenants or environments |
| **Sessions** | Tracks agent conversations with start/end timestamps and optional episode assignment |
| **Webhooks** | Register HTTP endpoints to receive event notifications (memory.extracted, agent.alert, etc.) |
| **Audit log** | Immutable record of every mutating API call, cursor-paginated |
| **Granular API keys** | Per-key scope restrictions (`memory:read`, `actions:write`, …) and agent-level restrictions |
| **MCP server** | Native integration with Claude Desktop and Claude Code via 9 MCP tools |
| **Prometheus metrics** | Auto HTTP metrics + 6 custom Gauges; Grafana dashboard included |
| **Python SDK** | Sync + async client backed by httpx; typed exceptions; retry with backoff |
| **TypeScript SDK** | Fetch-based client for Node.js 18+ and browsers; same types as the REST API |
| **CLI** | `crewlayer` command — manage agents, memory, actions, and portability from the terminal |
| **Multi-tenant** | Every resource is scoped to a tenant; isolation enforced at query level |

---

## Quickstart

### Option A — CLI (recommended)

```bash
pip install crewlayer[cli]
crewlayer init               # wizard: enter URL + API key
crewlayer tenants create --name "my-project"   # prints bootstrap key
crewlayer agents create --name "research-agent"
crewlayer memory recall <agent_id> "user preferences"
```

### Option B — curl

### 1. Create a tenant

```bash
curl -X POST http://localhost:8000/v1/tenants \
  -H "Content-Type: application/json" \
  -d '{"name": "my-project"}'
```

```json
{
  "id": "...",
  "name": "my-project",
  "initial_api_key": "crwl_<id>_<secret>"
}
```

Save the `initial_api_key` — it won't be shown again.

### 2. Create an agent

```bash
curl -X POST http://localhost:8000/v1/agents \
  -H "X-API-Key: crwl_..." \
  -H "Content-Type: application/json" \
  -d '{"name": "research-agent"}'
```

### 3. Store and recall memories

```bash
# Save a memory
curl -X POST http://localhost:8000/v1/agents/<agent_id>/memory \
  -H "X-API-Key: crwl_..." \
  -d '{"content": "User prefers concise answers", "importance": 0.9}'

# Semantic recall
curl -X POST http://localhost:8000/v1/agents/<agent_id>/memory/recall \
  -H "X-API-Key: crwl_..." \
  -d '{"query": "communication style", "limit": 5}'
```

### 4. Log an action

```bash
curl -X POST http://localhost:8000/v1/agents/<agent_id>/actions \
  -H "X-API-Key: crwl_..." \
  -d '{
    "tool_name": "web_search",
    "input_params": {"query": "FastAPI"},
    "output_result": {"results": ["..."]},
    "status": "success",
    "duration_ms": 320
  }'
```

### 5. Shared blackboard

```bash
# Write
curl -X PUT http://localhost:8000/v1/context/shared/system_prompt \
  -H "X-API-Key: crwl_..." \
  -d '{"value": {"text": "You are a helpful assistant"}}'

# Read
curl http://localhost:8000/v1/context/shared/system_prompt \
  -H "X-API-Key: crwl_..."
```

---

## SDKs

### Python

```bash
pip install ./sdk
```

```python
from crewlayer import CrewLayerClient

client = CrewLayerClient(api_key="crwl_...")

# Append to session history and extract long-term memories
client.memory.append(agent_id="...", session_id="...", role="user", content="User prefers Python")
client.memory.extract(agent_id="...", session_id="...")

# Semantic recall
results = client.memory.recall(agent_id="...", query="language preference", limit=5)

# Log an action
client.actions.log(
    agent_id="...",
    tool_name="send_email",
    input_params={"to": "user@example.com"},
    output_result={"status": "sent"},
    status="success",
)
```

### TypeScript / JavaScript

```bash
npm install crewlayer
# or from source:
npm install ./sdk-typescript
```

```typescript
import { CrewLayerClient } from "crewlayer";

const client = new CrewLayerClient({ apiKey: "crwl_..." });

// Append to session history
await client.memory.append({
  agentId: "...",
  sessionId: "...",
  role: "user",
  content: "User prefers Python",
});

// Semantic recall
const { results } = await client.memory.recall({
  agentId: "...",
  query: "language preference",
  limit: 5,
});

// Log an action
await client.actions.log({
  agentId: "...",
  toolName: "send_email",
  inputParams: { to: "user@example.com" },
  outputResult: { status: "sent" },
  status: "success",
});

// Subscribe to real-time context updates
const stream = client.context.subscribe({ namespace: "project:xyz", key: "status" });
stream.on("updated", (entry) => console.log(entry.value));
stream.close(); // when done
```

---

## API endpoints

### Auth / Tenants

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/tenants` | Create tenant (returns bootstrap API key) |
| `POST` | `/v1/api-keys` | Create additional API key |
| `GET` | `/v1/api-keys` | List API keys |
| `DELETE` | `/v1/api-keys/{key_id}` | Revoke API key |

### Agents

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/agents` | Create agent |
| `GET` | `/v1/agents` | List agents (filter by `?status=`, `?tags=`) |
| `GET` | `/v1/agents/{id}` | Get agent |
| `PATCH` | `/v1/agents/{id}` | Update agent |
| `DELETE` | `/v1/agents/{id}` | Delete agent |
| `GET` | `/v1/agents/{id}/status` | Get status (Redis-cached) |
| `PATCH` | `/v1/agents/{id}/status` | Set status (idle/working/error) |
| `GET` | `/v1/agents/tags` | List all tags with usage counts |
| `POST` | `/v1/agents/{id}/tags` | Add tags |
| `DELETE` | `/v1/agents/{id}/tags/{tag}` | Remove a tag |
| `GET` | `/v1/agents/{id}/alerts/config` | Get alert thresholds |
| `PATCH` | `/v1/agents/{id}/alerts/config` | Update alert thresholds |
| `POST` | `/v1/agents/{id}/relations` | Set a relation to another agent |
| `GET` | `/v1/agents/{id}/relations` | List all relations |
| `GET` | `/v1/agents/{id}/tree` | Hierarchical relation tree |
| `DELETE` | `/v1/agents/{id}/relations/{other_id}` | Remove a relation |
| `GET` | `/v1/agents/{id}/export` | Export agent snapshot (StreamingResponse) |
| `POST` | `/v1/agents/import` | Import a snapshot; returns new agent + id_map |

### Memory

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/agents/{id}/memory` | Save a memory (auto-deduplicates) |
| `POST` | `/v1/agents/{id}/memory/recall` | Semantic recall (active memories only) |
| `POST` | `/v1/agents/{id}/memory/extract` | Extract facts from conversation with Claude |
| `GET` | `/v1/agents/{id}/memory` | List memories (`?include_archived=true` for archived) |
| `DELETE` | `/v1/agents/{id}/memory/{memory_id}` | Soft-delete a memory |
| `GET` | `/v1/agents/{id}/memory/messages` | Short-term session history |
| `POST` | `/v1/agents/{id}/memory/messages` | Append to session history |
| `GET` | `/v1/agents/{id}/memories/{memory_id}/history` | Merge lineage (BFS ancestors) |
| `GET` | `/v1/agents/{id}/memories/stats` | Aggregate stats (active, archived, avg importance) |
| `POST` | `/v1/agents/{id}/memories/archive` | Force-archive memories below threshold |

### Actions

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/agents/{id}/actions` | Log an action |
| `GET` | `/v1/agents/{id}/actions` | List actions (cursor paginated) |
| `GET` | `/v1/agents/{id}/actions/{action_id}` | Get one action |
| `GET` | `/v1/agents/{id}/actions/stats` | Aggregate stats (total, error rate, avg duration) |

### Sessions

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/sessions` | Start a session |
| `GET` | `/v1/sessions/{id}` | Get session |
| `POST` | `/v1/sessions/{id}/close` | Close a session |
| `PATCH` | `/v1/sessions/{id}` | Update session (e.g. assign episode) |

### Episodes

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/agents/{id}/episodes` | Create an episode |
| `GET` | `/v1/agents/{id}/episodes` | List episodes (filter by `?status=`) |
| `GET` | `/v1/agents/{id}/episodes/{ep_id}` | Episode detail (with sessions + memories) |
| `POST` | `/v1/agents/{id}/episodes/{ep_id}/complete` | Complete episode; generates Claude summary |
| `POST` | `/v1/agents/{id}/episodes/{ep_id}/recall` | Semantic recall scoped to this episode |

### Context (Blackboard)

| Method | Path | Description |
|---|---|---|
| `PUT` | `/v1/context/{namespace}/{key}` | Write (optimistic locking, TTL, propagation optional) |
| `GET` | `/v1/context/{namespace}/{key}` | Read |
| `GET` | `/v1/context/{namespace}` | List namespace |
| `DELETE` | `/v1/context/{namespace}/{key}` | Delete |
| `GET` | `/v1/context/{namespace}/{key}/subscribe` | SSE stream — real-time updates |
| `GET` | `/v1/context/{namespace}/{key}/history` | Immutable write history (cursor-paginated) |
| `GET` | `/v1/context/{namespace}/{key}/history/{version}` | Point-in-time value |
| `POST` | `/v1/context/{namespace}/{key}/rollback` | Restore a previous version |

### Webhooks

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/webhooks` | Register webhook |
| `GET` | `/v1/webhooks` | List webhooks |
| `DELETE` | `/v1/webhooks/{id}` | Delete webhook |

### Audit Log

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/audit-log` | Cursor-paginated immutable audit log |

### Observability

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/metrics` | Prometheus metrics (auth required from non-localhost) |
| `GET` | `/v1/usage` | Resource usage stats for the current tenant |

---

## Environment variables

```env
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/crewlayer
REDIS_URL=redis://localhost:6379
SECRET_KEY=<random 32+ bytes>
EMBEDDING_PROVIDER=anthropic   # or "local"

# Optional
METRICS_TOKEN=<token>          # protects /metrics from non-localhost IPs
MCP_PORT=8001                  # MCP server SSE port
MCP_TRANSPORT=stdio            # "stdio" or "sse"
CREWLAYER_API_KEY=crwl_...     # API key used by the MCP server
```

---

## Conectar con Claude

CrewLayer incluye un servidor MCP que expone sus funciones como herramientas nativas para Claude.

### Claude Code (CLI)

```bash
claude mcp add crewlayer -- python -m mcp.server
```

O manualmente en la configuración MCP:

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

### Claude Desktop

Añadir el mismo bloque `mcpServers` a `~/Library/Application Support/Claude/claude_desktop_config.json` (Mac) o `%APPDATA%\Claude\claude_desktop_config.json` (Windows).

Una vez configurado, Claude puede usar directamente `memory_recall`, `action_log`, `context_write` y el resto de las 9 herramientas sin código adicional.

---

## Observabilidad

```bash
docker compose -f docker-compose.observability.yml up -d
```

- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000 (admin/admin)

Importar el dashboard: Grafana → Dashboards → Import → subir `observability/grafana/dashboards/crewlayer.json`.

El dashboard incluye: latencia HTTP (p50/p95/p99), memories activas vs archivadas, agents por estado, sessions activas, action log entries, tasa de errores.

---

## CLI

The official command-line interface lets you manage CrewLayer resources from your terminal without writing code.

### Install

```bash
pip install crewlayer[cli]
# or, from source:
pip install -e ".[cli]"
```

### Setup

```bash
crewlayer init
```

Runs an interactive wizard — enter the API base URL and your API key. Config is saved to `~/.crewlayer/config.json`.

```
CrewLayer Setup Wizard
──────────────────────
API base URL [http://localhost:8000]:
API key: ****

✓ Connection OK
Config saved to /home/user/.crewlayer/config.json
```

### Tenants & keys

```bash
# Create a new tenant (prints a bootstrap API key — save it!)
crewlayer tenants create --name "mi proyecto"

# Create a scoped API key for production
crewlayer keys create --name "produccion" --scopes "memory:read,memory:write"

# List all keys
crewlayer keys list
```

### Agents

```bash
# List all agents (optional tag filter)
crewlayer agents list
crewlayer agents list --tags produccion
crewlayer agents list --status error

# Create an agent
crewlayer agents create --name "asistente" --tags "ventas,soporte"

# Check status (Redis-cached idle/working/error)
crewlayer agents status <agent_id>
```

### Memory

```bash
# Semantic recall
crewlayer memory recall <agent_id> "preferencias del usuario"
crewlayer memory recall <agent_id> "historial de compras" --limit 5

# List memories (paginated)
crewlayer memory list <agent_id>
crewlayer memory list <agent_id> --limit 50 --archived
```

### Actions

```bash
# List action history
crewlayer actions list <agent_id>
crewlayer actions list <agent_id> --status error --limit 50

# Aggregate stats (error rate, avg duration, per-tool breakdown)
crewlayer actions stats <agent_id>
```

### Export / Import

```bash
# Export full agent backup (memories, actions, episodes, …)
crewlayer export <agent_id> --output agent_backup.json

# Import into the same or a different tenant (creates a new agent ID)
crewlayer import agent_backup.json
```

### JSON output for pipelines

Every list and status command accepts `--json` to print raw JSON to stdout:

```bash
# Pipe into jq
crewlayer agents list --json | jq '.[].id'

# Use in scripts
AGENT_ID=$(crewlayer agents create --name "bot" --json | jq -r '.id')
crewlayer memory recall "$AGENT_ID" "context" --json | jq '.results[].content'
```

---

## Running tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

316 Python tests run against a real PostgreSQL and Redis instance (no mocks for infrastructure). CLI tests use httpx mocks and require no running server. TypeScript SDK: 72 tests with vitest (fetch mocked, no server needed).

---

## License

MIT
