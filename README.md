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
| **Action log** | Immutable, append-only record of every tool call with cursor pagination and aggregate stats |
| **Shared blackboard** | Namespace-scoped key/value store with optimistic locking and real-time SSE subscriptions |
| **Agent status** | idle/working/error lifecycle, Redis-cached, auto-transitions on session open/close |
| **Sessions** | Tracks agent conversations with start/end timestamps and status |
| **Webhooks** | Register HTTP endpoints to receive event notifications (memory.extracted, etc.) |
| **Audit log** | Immutable record of every mutating API call, cursor-paginated |
| **Granular API keys** | Per-key scope restrictions (`memory:read`, `actions:write`, …) and agent-level restrictions |
| **MCP server** | Native integration with Claude Desktop and Claude Code via 9 MCP tools |
| **Prometheus metrics** | Auto HTTP metrics + 6 custom Gauges; Grafana dashboard included |
| **Multi-tenant** | Every resource is scoped to a tenant; isolation enforced at query level |

---

## Quickstart

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

## Python SDK

```bash
pip install ./sdk
```

```python
from crewlayer import CrewLayerClient

client = CrewLayerClient(api_key="crwl_...")

# Store a memory
client.memory.save(agent_id="...", content="User prefers Python")

# Recall by semantic similarity
results = client.memory.recall(agent_id="...", query="language preference")

# Log an action
client.actions.log(
    agent_id="...",
    tool_name="send_email",
    input_params={"to": "user@example.com"},
    output_result={"status": "sent"},
    status="success",
)
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
| `GET` | `/v1/agents` | List agents (filter by `?status=`) |
| `GET` | `/v1/agents/{id}` | Get agent |
| `DELETE` | `/v1/agents/{id}` | Delete agent |
| `GET` | `/v1/agents/{id}/status` | Get status (Redis-cached) |
| `PATCH` | `/v1/agents/{id}/status` | Set status (idle/working/error) |

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
| `POST` | `/v1/agents/{id}/sessions` | Start a session |
| `GET` | `/v1/agents/{id}/sessions` | List sessions |
| `GET` | `/v1/agents/{id}/sessions/{session_id}` | Get session |
| `POST` | `/v1/agents/{id}/sessions/{session_id}/end` | End a session |

### Context (Blackboard)

| Method | Path | Description |
|---|---|---|
| `PUT` | `/v1/context/{namespace}/{key}` | Write (optimistic locking optional) |
| `GET` | `/v1/context/{namespace}/{key}` | Read |
| `GET` | `/v1/context/{namespace}` | List namespace |
| `DELETE` | `/v1/context/{namespace}/{key}` | Delete |
| `GET` | `/v1/context/{namespace}/{key}/subscribe` | SSE stream — real-time updates |

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

## Running tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

240 tests run against a real PostgreSQL and Redis instance (no mocks for infrastructure).

---

## License

MIT
