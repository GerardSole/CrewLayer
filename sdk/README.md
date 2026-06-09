# CrewLayer Python SDK

Official Python client for the [CrewLayer](https://github.com/your-org/crewlayer) AI agent backend.

## Install

```bash
pip install crewlayer
```

Requires Python 3.12+. The only runtime dependency is `httpx`.

---

## Quick start

```python
from crewlayer import CrewLayerClient

client = CrewLayerClient(api_key="crwl_...")

# Short-term memory — append a message to a session
client.memory.append(
    agent_id="agent-uuid",
    role="user",
    content="What are my preferences?",
    session_id="session-abc",
)

# Semantic recall from long-term memory
results = client.memory.recall(
    agent_id="agent-uuid",
    query="user preferences",
    limit=5,
)
for item in results.results:
    print(f"[{item.similarity:.2f}] {item.content}")

# Log an action
client.actions.log(
    agent_id="agent-uuid",
    tool_name="send_email",
    input_params={"to": "user@example.com", "subject": "Hello"},
    output_result={"message_id": "msg_123"},
    status="success",
    duration_ms=230,
)

client.close()
```

---

## Async client

```python
import asyncio
from crewlayer import CrewLayerAsyncClient

async def main() -> None:
    async with CrewLayerAsyncClient(api_key="crwl_...") as client:
        await client.memory.append(
            agent_id="agent-uuid",
            role="assistant",
            content="Here are your preferences...",
        )
        page = await client.memory.list(agent_id="agent-uuid", page=1, page_size=20)
        print(f"{page.total} memories stored")

asyncio.run(main())
```

---

## Memory

### Short-term memory (Redis, TTL-based)

```python
# Append a message to a session
short = client.memory.append(
    agent_id="agent-uuid",
    role="user",
    content="Remember: I prefer dark mode.",
    session_id="session-xyz",
    metadata={"source": "chat"},
)
print(short.count)  # number of messages in session

# Read recent messages (newest first)
short = client.memory.messages(agent_id="agent-uuid", session_id="session-xyz", limit=20)
for msg in short.messages:
    print(f"{msg.role}: {msg.content}")
```

### Long-term memory (PostgreSQL + pgvector)

```python
# Extract facts from a conversation and persist them
result = client.memory.extract(
    agent_id="agent-uuid",
    conversation="User: I love Python and hate Java.\nAssistant: Got it!",
)
print(f"Extracted {result.extracted_count} facts: {result.memory_ids}")

# Semantic recall
results = client.memory.recall(
    agent_id="agent-uuid",
    query="programming language preferences",
    limit=5,
    min_similarity=0.7,
)
for item in results.results:
    print(f"[{item.similarity:.2f}] {item.content}  tags={item.tags}")

# List all memories (paginated)
page = client.memory.list(agent_id="agent-uuid", page=1, page_size=20)
print(f"Total: {page.total}")

# Soft-delete a memory
client.memory.delete(agent_id="agent-uuid", memory_id="memory-uuid")
```

---

## Actions

```python
# Log an action
action = client.actions.log(
    agent_id="agent-uuid",
    tool_name="web_search",
    input_params={"query": "FastAPI tutorial"},
    output_result={"results": ["fastapi.tiangolo.com"]},
    status="success",          # "success" | "error" | "timeout"
    duration_ms=320,
    metadata={"model": "gpt-4"},
)
print(action.id, action.timestamp)

# Retrieve a specific action
action = client.actions.get(agent_id="agent-uuid", action_id=action.id)

# List with filters
page = client.actions.list(
    agent_id="agent-uuid",
    tool="send_email",
    status="error",
    limit=50,
)
while page.next_cursor:
    page = client.actions.list(
        agent_id="agent-uuid",
        cursor=page.next_cursor,
        limit=50,
    )

# Aggregate stats
stats = client.actions.stats(agent_id="agent-uuid")
print(f"Total: {stats.total_actions}, error rate: {stats.error_rate:.1%}")
for tool in stats.by_tool:
    print(f"  {tool.tool_name}: {tool.count} calls, {tool.error_rate:.1%} errors")
```

---

## Context (shared blackboard)

The blackboard lets multiple agents share state within the same tenant.

```python
# Write a value (creates or overwrites)
entry = client.context.write(
    namespace="pipeline-run-42",
    key="status",
    value={"phase": "ingestion", "progress": 0.3},
)
print(entry.version)  # 1

# Read it back
entry = client.context.read("pipeline-run-42", "status")
print(entry.value["phase"])  # "ingestion"

# Optimistic locking: only update if version matches what we read
updated = client.context.write(
    namespace="pipeline-run-42",
    key="status",
    value={"phase": "processing", "progress": 0.7},
    expected_version=entry.version,  # raises ConflictError if stale
)

# Use expected_version=0 to assert the key must not yet exist
client.context.write(
    namespace="locks",
    key="worker-1",
    value={"locked_at": "2024-01-01T00:00:00Z"},
    expected_version=0,  # ConflictError if another worker already set this
)

# Write with TTL (auto-expires after 1 hour)
client.context.write(
    namespace="cache",
    key="user-profile",
    value={"name": "Alice"},
    expires_at="2024-01-01T01:00:00Z",
)

# List all entries in a namespace
ns = client.context.list_namespace("pipeline-run-42")
for e in ns.entries:
    print(f"{e.key} = {e.value}  (v{e.version})")

# Delete an entry
client.context.delete("pipeline-run-42", "status")
```

---

## Error handling

```python
from crewlayer import (
    CrewLayerClient,
    AuthError,
    NotFoundError,
    ConflictError,
    RateLimitError,
    ServerError,
    CrewLayerError,
)

try:
    client.memory.recall(agent_id="bad-id", query="test")
except AuthError:
    print("Invalid API key")
except NotFoundError:
    print("Agent not found")
except ConflictError as e:
    print(f"Version conflict: {e}")
except RateLimitError:
    print("Rate limited — back off and retry")
except ServerError as e:
    print(f"Server error (status {e.status_code}) after retries: {e}")
except CrewLayerError as e:
    print(f"Unexpected error: {e}")
```

All exceptions expose:
- `e.status_code` — HTTP status code (`int | None`)
- `e.response` — parsed JSON body (`dict | None`)

---

## Retry behaviour

The SDK automatically retries on `500`, `502`, `503`, `504` responses with exponential backoff:

| Attempt | Wait before retry |
|---------|-------------------|
| 1st retry | 1 s |
| 2nd retry | 2 s |
| 3rd retry | 4 s |

After 3 retries the last response raises `ServerError`. Network-level errors (`httpx.TransportError`) are retried with the same schedule.

---

## Configuration

```python
client = CrewLayerClient(
    api_key="crwl_...",
    base_url="https://api.your-deployment.com",  # default: http://localhost:8000
)
```
