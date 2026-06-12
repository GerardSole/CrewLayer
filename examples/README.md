# CrewLayer Examples

Runnable scripts that demonstrate CrewLayer working end-to-end.
Start with `quickstart.py` and work your way down.

---

## Prerequisites (all examples)

```bash
# 1. Start the backend
docker compose up -d        # PostgreSQL + Redis
alembic upgrade head
uvicorn main:app --reload   # API at http://localhost:8000

# 2. Install the SDK
pip install crewlayer

# 3. Set common env vars
export CREWLAYER_API_KEY=crwl_...
export CREWLAYER_URL=http://localhost:8000
export CREWLAYER_AGENT_ID=<your-agent-uuid>  # create one via POST /v1/agents
```

---

## Examples

| File | What it shows | Extra requirements |
|---|---|---|
| [quickstart.py](#quickstartpy) | Memory, recall, actions, blackboard in ~30 lines | `pip install crewlayer` |
| [langchain_conversation.py](#langchain_conversationpy) | Multi-turn chat with persistent LangChain memory | `pip install crewlayer[langchain] langchain langchain-openai` + `OPENAI_API_KEY` |
| [autogen_multiagent.py](#autogen_multiagentpy) | Two AutoGen agents + shared blackboard | `pip install crewlayer[autogen] pyautogen` + `OPENAI_API_KEY` |
| [llamaindex_rag.py](#llamaindex_ragpy) | Index 3 docs, run semantic queries, log actions | `pip install crewlayer[llamaindex] llama-index-core` |
| [nextjs_chatbot/](nextjs_chatbot/) | Full Next.js streaming chatbot with memory | Node.js 18+, `npm install crewlayer ai @ai-sdk/anthropic` |

---

## quickstart.py

**The best starting point.** Exercises every core primitive in under 30 lines.

```bash
python examples/quickstart.py
```

**Output:**
```
Saving memories...
  ✓ The user prefers Python over JavaScript
  ✓ The user is building a multi-agent RAG pipeline
  ✓ The user wants responses in Spanish

Recalling memories about 'programming language'...
  [0.91] The user prefers Python over JavaScript
  [0.74] The user is building a multi-agent RAG pipeline

Logging action...
  ✓ Action logged: act_01jx...

Writing to blackboard...
  ✓ Written (version 1)
  ✓ Read back: {'phase': 'done', 'memories': 2}

All done! CrewLayer is working correctly.
```

---

## langchain_conversation.py

Multi-turn conversation where **every message is stored in CrewLayer**.
Run the script twice — on the second run the chain loads the previous conversation
from Redis and the model knows what was discussed before.

```bash
pip install crewlayer[langchain] langchain langchain-openai
export OPENAI_API_KEY=sk-...
python examples/langchain_conversation.py
python examples/langchain_conversation.py   # memory persists across runs
```

Key classes:
- `CrewLayerMemory` — `BaseChatMemory` backed by CrewLayer Redis session store
- `CrewLayerCallbackHandler` — logs every LangChain tool call as a CrewLayer action

---

## autogen_multiagent.py

A **researcher** and a **writer** agent collaborate via AutoGen.
`CrewLayerGroupChatManager` writes every turn to a shared blackboard so any
external process can track the live conversation state.

```bash
pip install crewlayer[autogen] pyautogen
export OPENAI_API_KEY=sk-...
export CREWLAYER_RESEARCHER_AGENT_ID=<uuid>
export CREWLAYER_WRITER_AGENT_ID=<uuid>
python examples/autogen_multiagent.py
```

After the chat, the script reads the blackboard and prints:
```
Last speaker : writer
Turn         : 4
Message      : "CrewLayer gives multi-agent systems a shared, persistent..."

agent:researcher
  message : "• CrewLayer stores memories in Redis (short-term)..."

agent:writer
  message : "CrewLayer is an open-source backend that..."
```

You can also read the blackboard from **any other process** while the chat is running:
```python
client.context.read("multiagent-demo", "latest_turn")
```

---

## llamaindex_rag.py

Index three documents into CrewLayer's pgvector store, then query them
semantically. Every query is automatically logged as a `llamaindex.query` action.

```bash
pip install crewlayer[llamaindex] llama-index-core
python examples/llamaindex_rag.py
```

Run twice to show persistence: the second run queries documents indexed in the first.

Key classes:
- `CrewLayerVectorIndex` — `insert()` stores docs as long-term memories, `similarity_search()` runs cosine search
- `CrewLayerQueryEngine` — wraps the index, logs every query as an action

---

## nextjs_chatbot/

A complete Next.js streaming chatbot using the Vercel AI SDK + CrewLayer TypeScript adapter.

```
nextjs_chatbot/
├── app/api/chat/route.ts   — streaming route handler (the only file you need)
└── README.md               — full setup instructions
```

See [nextjs_chatbot/README.md](nextjs_chatbot/README.md) for step-by-step setup.
The route handler uses:
- `crewLayerMemory()` — recalls relevant memories before each LLM call
- `crewLayerTools()` — exposes `recall_memory` and `write_context` to the model
- `CrewLayerDataStream` — streams the response and logs it as an action
