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
| **Memory extraction** | Claude claude-opus-4-8 extracts facts from conversations automatically |
| **Action log** | Immutable, append-only record of every tool call with cursor pagination |
| **Shared blackboard** | Namespace-scoped key/value store for multi-agent coordination, with optimistic locking |
| **Multi-tenant** | Every resource is scoped to a tenant; isolation enforced at query level |
| **API key auth** | Keys encoded with their own ID for O(1) lookup; bcrypt-hashed |

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
| `GET` | `/v1/agents` | List agents |
| `GET` | `/v1/agents/{id}` | Get agent |
| `DELETE` | `/v1/agents/{id}` | Delete agent |

### Memory

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/agents/{id}/memory` | Save a memory |
| `POST` | `/v1/agents/{id}/memory/recall` | Semantic recall |
| `POST` | `/v1/agents/{id}/memory/extract` | Extract facts from conversation |
| `GET` | `/v1/agents/{id}/memory` | List memories (paginated) |
| `DELETE` | `/v1/agents/{id}/memory/{memory_id}` | Soft-delete a memory |
| `GET/POST` | `/v1/agents/{id}/memory/short/{session_id}` | Short-term session history |

### Actions

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/agents/{id}/actions` | Log an action |
| `GET` | `/v1/agents/{id}/actions` | List actions (cursor paginated) |
| `GET` | `/v1/agents/{id}/actions/{action_id}` | Get one action |
| `GET` | `/v1/agents/{id}/actions/stats` | Aggregate stats |

### Context (Blackboard)

| Method | Path | Description |
|---|---|---|
| `PUT` | `/v1/context/{namespace}/{key}` | Write (optimistic locking optional) |
| `GET` | `/v1/context/{namespace}/{key}` | Read |
| `GET` | `/v1/context/{namespace}` | List namespace |
| `DELETE` | `/v1/context/{namespace}/{key}` | Delete |

---

## Environment variables

```env
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/crewlayer
REDIS_URL=redis://localhost:6379
SECRET_KEY=<random 32+ bytes>
EMBEDDING_PROVIDER=anthropic   # or "local"
```

---

## Running tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

All 52 tests run against a real PostgreSQL and Redis instance (no mocks for infrastructure).

---

## License

MIT
