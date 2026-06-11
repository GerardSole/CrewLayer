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

---

## Integrations

### LangChain

Install the extra:

```bash
pip install crewlayer[langchain]
```

#### `AgentLayerMemory` — `BaseChatMemory` backed by CrewLayer

Plug-and-play replacement for `ConversationBufferMemory`. Messages are persisted in CrewLayer's
Redis session store and rehydrated on every chain call.

```python
from crewlayer import CrewLayerClient
from crewlayer.integrations.langchain import AgentLayerMemory
from langchain.chains import ConversationChain
from langchain_openai import ChatOpenAI

client = CrewLayerClient(api_key="crwl_...")
memory = AgentLayerMemory(
    client=client,
    agent_id="agent-uuid",
    session_id="user-123",    # one session per user / conversation
    memory_key="history",     # must match your prompt template
    return_messages=True,     # return Message objects (default); False = plain string
)

chain = ConversationChain(llm=ChatOpenAI(), memory=memory)
chain.predict(input="What's the capital of France?")
```

#### `AgentLayerVectorStore` — LangChain `VectorStore` backed by pgvector

`similarity_search` delegates to CrewLayer semantic recall (cosine similarity via pgvector).
`add_texts` persists texts as long-term memories via the extract endpoint.

```python
from crewlayer.integrations.langchain import AgentLayerVectorStore

store = AgentLayerVectorStore(client=client, agent_id="agent-uuid", k=4)

# Add documents (stored as long-term memories)
store.add_texts(["User prefers dark mode", "User is a Python developer"])

# Semantic search
docs = store.similarity_search("programming preferences", k=3)
for doc in docs:
    print(f"[{doc.metadata['similarity']:.2f}] {doc.page_content}")

# With scores
results = store.similarity_search_with_score("dark mode", k=2)
for doc, score in results:
    print(f"[{score:.2f}] {doc.page_content}")
```

#### `AgentLayerCallbackHandler` — auto-log every tool call

Attach to any chain or agent executor to automatically record tool invocations as
CrewLayer action entries (name, input, output, duration).

```python
from crewlayer.integrations.langchain import AgentLayerCallbackHandler
from langchain.agents import AgentExecutor

handler = AgentLayerCallbackHandler(
    client=client,
    agent_id="agent-uuid",
    session_id="session-abc",  # optional
)

agent_executor = AgentExecutor(agent=agent, tools=tools)
agent_executor.invoke({"input": "Search the web for X"}, config={"callbacks": [handler]})
```

---

### CrewAI

Install the extra:

```bash
pip install crewlayer[crewai]
```

#### `AgentLayerMemoryProvider` — CrewAI storage backed by CrewLayer

Implements the CrewAI `Storage` interface (`save` / `search` / `reset`).
Pass it as the `storage=` argument to any CrewAI memory class.

```python
from crewlayer import CrewLayerClient
from crewlayer.integrations.crewai import AgentLayerMemoryProvider
from crewai.memory import LongTermMemory

client = CrewLayerClient(api_key="crwl_...")
storage = AgentLayerMemoryProvider(
    client=client,
    agent_id="agent-uuid",
    session_id="default",     # session for short-term writes
    recall_limit=5,           # default number of results from search()
    min_similarity=0.35,      # minimum cosine similarity for recall
)
ltm = LongTermMemory(storage=storage)
```

Direct usage (without a CrewAI memory wrapper):

```python
storage.save("The user prefers Python over JavaScript", metadata={"source": "chat"})
results = storage.search("programming language preferences", limit=3)
for r in results:
    print(f"[{r['score']:.2f}] {r['memory']}")
```

#### `AgentLayerTaskLogger` — log every CrewAI task completion

Pass an instance as `callback=` on any `Task`.  When the task finishes, the result is
recorded as a CrewLayer action entry (tool_name = task description, status = success).

```python
from crewlayer.integrations.crewai import AgentLayerTaskLogger
from crewai import Agent, Task, Crew

logger = AgentLayerTaskLogger(
    client=client,
    agent_id="agent-uuid",
    session_id="session-abc",  # optional
)

task = Task(
    description="Summarize customer feedback",
    expected_output="A short paragraph summary",
    agent=my_agent,
    callback=logger,
)
crew = Crew(agents=[my_agent], tasks=[task])
crew.kickoff()
```

---

### LlamaIndex

Install the extra:

```bash
pip install crewlayer[llamaindex]
```

#### `CrewLayerMemoryBuffer` — `BaseMemory` backed by CrewLayer

Drop-in replacement for `ChatMemoryBuffer`.  Each `put()` appends to the
agent's Redis session store; `get()` fetches recent messages as `ChatMessage` objects.

```python
from crewlayer import CrewLayerClient
from crewlayer.integrations.llamaindex import CrewLayerMemoryBuffer
from llama_index.core.chat_engine import CondenseQuestionChatEngine

client = CrewLayerClient(api_key="crwl_...")
memory = CrewLayerMemoryBuffer(
    client=client,
    agent_id="agent-uuid",
    session_id="user-123",  # one session per user / conversation
    limit=50,               # max messages returned by get()
)

# Use directly
memory.put(ChatMessage(role="user", content="Hello!"))
msgs = memory.get()
```

#### `CrewLayerVectorIndex` — index backed by pgvector semantic recall

`insert()` persists documents as long-term memories via the extract endpoint.
`similarity_search()` delegates to CrewLayer's pgvector cosine similarity.
`as_query_engine()` returns a `CrewLayerQueryEngine` that logs every query
as a `llamaindex.query` action.

```python
from crewlayer.integrations.llamaindex import CrewLayerVectorIndex
from llama_index.core.schema import Document

index = CrewLayerVectorIndex(
    client=client,
    agent_id="agent-uuid",
    similarity_top_k=4,     # default number of results
    min_similarity=0.0,     # minimum cosine similarity
)

# Add documents
index.insert(Document(text="The user's name is Alice and she prefers dark mode."))

# Direct similarity search (returns MemoryItem list)
items = index.similarity_search("user interface preferences", top_k=3)
for item in items:
    print(f"[{item.similarity:.2f}] {item.content}")
```

#### `CrewLayerQueryEngine` — query engine with automatic action logging

Returned by `index.as_query_engine()`.  Every `query()` call retrieves
memories, logs a `llamaindex.query` action (including duration and result
count), and returns a `QueryResponse` with `.response` (str) and
`.source_nodes` (list of `MemoryItem`).

```python
engine = index.as_query_engine(
    session_id="session-abc",   # optional, associated with logged actions
    similarity_top_k=5,         # overrides index default
)

response = engine.query("¿qué recuerdas sobre el cliente?")
print(response.response)         # concatenated memory contents
print(len(response.source_nodes))  # number of memories retrieved
```

#### `CrewLayerCallbackManager` — log LLM and tool calls

Implements `BaseCallbackHandler`.  Add it to LlamaIndex's `CallbackManager`
to automatically record every LLM call, function call, and agent step as
an action entry (tool_names: `llamaindex.llm`, `llamaindex.function_call`,
`llamaindex.agent_step`).

```python
from crewlayer.integrations.llamaindex import CrewLayerCallbackManager
from llama_index.core.callbacks import CallbackManager
from llama_index.llms.openai import OpenAI

handler = CrewLayerCallbackManager(
    client=client,
    agent_id="agent-uuid",
    session_id="session-abc",  # optional
)
llm = OpenAI(callback_manager=CallbackManager([handler]))
```

---

### AutoGen (Microsoft)

> **This is where CrewLayer makes the biggest difference.**
> Multi-agent workflows need a shared, persistent blackboard so every agent
> can see what others are doing — without passing giant context windows around.
> `CrewLayerGroupChatManager` maintains that blackboard automatically after
> every turn.  Any agent (or external observer) can call
> `client.context.read(group_id, "latest_turn")` to get the current state.

Install the extra:

```bash
pip install crewlayer[autogen]
```

#### `CrewLayerConversableAgent` — auto-persist every message

Drop-in replacement for `autogen.ConversableAgent`.  Every message sent or
received is automatically:
- appended to CrewLayer short-term memory (durable conversation history)
- logged as an action entry (full audit trail with `duration_ms`)

The incoming message is saved to memory *before* AutoGen processes it, so the
history survives even if the LLM call later raises.

```python
from crewlayer import CrewLayerClient
from crewlayer.integrations.autogen import CrewLayerConversableAgent
import autogen

client = CrewLayerClient(api_key="crwl_...")

researcher = CrewLayerConversableAgent(
    name="researcher",
    client=client,
    agent_id="<uuid-researcher>",
    session_id="project-alpha",   # groups this conversation in short-term memory
    system_message="You are a research assistant.",
    llm_config={"config_list": [{"model": "gpt-4", "api_key": "..."}]},
)

writer = CrewLayerConversableAgent(
    name="writer",
    client=client,
    agent_id="<uuid-writer>",
    session_id="project-alpha",
    system_message="You are a technical writer.",
    llm_config={"config_list": [{"model": "gpt-4", "api_key": "..."}]},
)

# Every send/receive is automatically logged
researcher.initiate_chat(writer, message="Summarise the latest CrewLayer release.")
```

#### `CrewLayerGroupChatManager` — shared blackboard for multi-agent groups

Extends `autogen.GroupChatManager`.  After **every turn** in the group chat,
two blackboard entries are written to the shared namespace:

| Key | Value |
|-----|-------|
| `latest_turn` | `{agent, content, turn}` — last speaker + message |
| `agent:{name}` | `{last_message, turn}` — per-agent most recent message |

Any agent or external service can read the live group state without being
part of the conversation.

```python
from crewlayer.integrations.autogen import (
    CrewLayerGroupChatManager,
    CrewLayerAgentMemory,
    sync_agent_status,
)

groupchat = autogen.GroupChat(
    agents=[researcher, writer],
    messages=[],
    max_round=12,
)
manager = CrewLayerGroupChatManager(
    client=client,
    group_id="project-alpha",    # blackboard namespace
    groupchat=groupchat,
    llm_config={"config_list": [{"model": "gpt-4", "api_key": "..."}]},
)

researcher.initiate_chat(manager, message="Let's plan the next release.")

# From anywhere — check who spoke last and what they said
state = manager.get_shared_context()
for entry in state.entries:
    print(f"{entry.key}: {entry.value}")

# Or read directly
latest = client.context.read("project-alpha", "latest_turn")
print(f"{latest.value['agent']}: {latest.value['content']}")
```

#### `CrewLayerAgentMemory` — load long-term memories as initial context

Enriches an agent's system message with relevant long-term memories before
the conversation starts.  Gives agents continuity across sessions without
manually managing context.

```python
from crewlayer.integrations.autogen import CrewLayerAgentMemory

# Load up to 5 memories relevant to "research context and history"
CrewLayerAgentMemory(
    client=client,
    agent_id="<uuid-researcher>",
    query="research context and history",
    limit=5,
).apply(researcher)   # prepends bullet-point memories to system_message

# Now start the chat — the researcher already knows its history
researcher.initiate_chat(manager, message="Continue from last time.")
```

#### `sync_agent_status` — keep CrewLayer in sync with AutoGen state

Maps AutoGen thinking/idle states to CrewLayer's `working`/`idle`/`error`
enum.  Call it around LLM calls to get real-time status in dashboards.

| AutoGen string | CrewLayer status |
|----------------|-----------------|
| `thinking`, `replying`, `generating`, `processing` | `working` |
| `idle`, `waiting` | `idle` |
| `error` | `error` |

```python
from crewlayer.integrations.autogen import sync_agent_status

sync_agent_status(client, agent_id="<uuid-researcher>", autogen_status="thinking")
response = researcher.generate_reply(messages)
sync_agent_status(client, agent_id="<uuid-researcher>", autogen_status="idle")
```
```
