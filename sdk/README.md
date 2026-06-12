# CrewLayer Python SDK

Open source memory & context backend for AI agents.
Persistent memory, action logging, and shared blackboard — all in one REST API.

[![PyPI](https://img.shields.io/pypi/v/crewlayer)](https://pypi.org/project/crewlayer/)
[![Python](https://img.shields.io/pypi/pyversions/crewlayer)](https://pypi.org/project/crewlayer/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/GerardSole/CrewLayer/blob/main/LICENSE)

**Source & docs:** [github.com/GerardSole/CrewLayer](https://github.com/GerardSole/CrewLayer)

---

## Install

```bash
pip install crewlayer
```

Requires Python 3.12+. Runtime dependency: `httpx` only.

---

## Quick start

```python
from crewlayer import CrewLayerClient

client = CrewLayerClient(api_key="crwl_...", base_url="http://localhost:8000")

# Persist a message to short-term memory
client.memory.append(agent_id="agent-uuid", role="user", content="I prefer dark mode")

# Semantic recall from long-term memory
results = client.memory.recall(agent_id="agent-uuid", query="UI preferences", limit=5)
for item in results.results:
    print(f"[{item.similarity:.2f}] {item.content}")

# Log an action (full audit trail)
client.actions.log(agent_id="agent-uuid", tool_name="web_search",
                   input_params={"q": "crewlayer"}, status="success", duration_ms=120)

# Shared blackboard between agents
client.context.write(namespace="project-42", key="phase", value={"stage": "planning"})
entry = client.context.read("project-42", "phase")
print(entry.value)   # {"stage": "planning"}

client.close()
```

---

## Async client

```python
import asyncio
from crewlayer import CrewLayerAsyncClient

async def main():
    async with CrewLayerAsyncClient(api_key="crwl_...") as client:
        await client.memory.append(agent_id="agent-uuid", role="user", content="Hello")
        result = await client.memory.recall(agent_id="agent-uuid", query="greeting")
        print(result.results)

asyncio.run(main())
```

---

## Integrations

Optional extras bring first-class support for popular AI frameworks.
Each integration falls back gracefully when the framework is not installed.

| Extra | Install | What you get |
|---|---|---|
| `langchain` | `pip install crewlayer[langchain]` | `AgentLayerMemory`, `AgentLayerVectorStore`, `AgentLayerCallbackHandler` |
| `crewai` | `pip install crewlayer[crewai]` | `AgentLayerMemoryProvider`, `AgentLayerTaskLogger` |
| `llamaindex` | `pip install crewlayer[llamaindex]` | `CrewLayerMemoryBuffer`, `CrewLayerVectorIndex`, `CrewLayerQueryEngine`, `CrewLayerCallbackManager` |
| `autogen` | `pip install crewlayer[autogen]` | `CrewLayerConversableAgent`, `CrewLayerGroupChatManager`, `CrewLayerAgentMemory`, `sync_agent_status` |
| `all-integrations` | `pip install crewlayer[all-integrations]` | All of the above |

### LangChain

```python
from crewlayer import CrewLayerClient
from crewlayer.integrations.langchain import AgentLayerMemory
from langchain.chains import ConversationChain
from langchain_openai import ChatOpenAI

client = CrewLayerClient(api_key="crwl_...")
memory = AgentLayerMemory(client=client, agent_id="agent-uuid", session_id="user-123")
chain = ConversationChain(llm=ChatOpenAI(), memory=memory)
chain.predict(input="What's my name?")
```

### CrewAI

```python
from crewlayer.integrations.crewai import AgentLayerMemoryProvider, AgentLayerTaskLogger
from crewai.memory import LongTermMemory
from crewai import Task

storage = AgentLayerMemoryProvider(client=client, agent_id="agent-uuid")
ltm = LongTermMemory(storage=storage)

logger = AgentLayerTaskLogger(client=client, agent_id="agent-uuid")
task = Task(description="Summarize feedback", expected_output="...", agent=agent, callback=logger)
```

### LlamaIndex

```python
from crewlayer.integrations.llamaindex import CrewLayerVectorIndex
from llama_index.core.schema import Document

index = CrewLayerVectorIndex(client=client, agent_id="agent-uuid", similarity_top_k=4)
index.insert(Document(text="User prefers dark mode"))
engine = index.as_query_engine()
response = engine.query("UI preferences")
print(response.response)
```

### AutoGen (multi-agent blackboard)

The killer feature: `CrewLayerGroupChatManager` writes every turn to a shared blackboard.
Any agent — or external observer — can read live group state without being in the chat.

```python
from crewlayer.integrations.autogen import (
    CrewLayerConversableAgent, CrewLayerGroupChatManager, CrewLayerAgentMemory,
)
import autogen

client = CrewLayerClient(api_key="crwl_...")
researcher = CrewLayerConversableAgent(name="researcher", client=client, agent_id="uuid-r",
                                       llm_config={"config_list": [...]})
writer = CrewLayerConversableAgent(name="writer", client=client, agent_id="uuid-w",
                                   llm_config={"config_list": [...]})

groupchat = autogen.GroupChat(agents=[researcher, writer], messages=[], max_round=10)
manager = CrewLayerGroupChatManager(client=client, group_id="project-alpha", groupchat=groupchat)
CrewLayerAgentMemory(client=client, agent_id="uuid-r").apply(researcher)

researcher.initiate_chat(manager, message="Let's plan the release.")

# From anywhere — see who spoke last
latest = client.context.read("project-alpha", "latest_turn")
print(latest.value)  # {"agent": "writer", "content": "...", "turn": 3}
```

---

## Error handling

```python
from crewlayer import CrewLayerError, AuthError, NotFoundError, ConflictError, RateLimitError

try:
    client.memory.recall(agent_id="bad-id", query="test")
except AuthError:
    print("Invalid API key")
except NotFoundError:
    print("Agent not found")
except ConflictError as e:
    print(f"Version conflict: {e}")
except RateLimitError:
    print("Rate limited")
except CrewLayerError as e:
    print(f"HTTP {e.status_code}: {e}")
```

All exceptions expose `.status_code` (int | None) and `.response` (dict | None).

---

## Self-hosting

```bash
git clone https://github.com/GerardSole/CrewLayer
cd CrewLayer
docker compose up -d       # starts PostgreSQL + Redis
alembic upgrade head
uvicorn main:app --reload  # API at http://localhost:8000
```

Full documentation: [github.com/GerardSole/CrewLayer](https://github.com/GerardSole/CrewLayer)
