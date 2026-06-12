"""
LangChain multi-turn conversation with persistent CrewLayer memory.

Demonstrates:
  - AgentLayerMemory: every message saved to Redis session store
  - AgentLayerCallbackHandler: every tool call logged as CrewLayer action
  - Persistence across runs: run the script twice to see memory carry over

Run:
    pip install crewlayer[langchain] langchain langchain-openai
    export CREWLAYER_API_KEY=crwl_...
    export CREWLAYER_AGENT_ID=<your-agent-uuid>
    export OPENAI_API_KEY=sk-...
    python examples/langchain_conversation.py
    python examples/langchain_conversation.py   # run again — memory persists!
"""
import os
import sys

from crewlayer import CrewLayerClient
from crewlayer.integrations.langchain import AgentLayerCallbackHandler, AgentLayerMemory

API_KEY   = os.environ.get("CREWLAYER_API_KEY", "")
BASE_URL  = os.environ.get("CREWLAYER_URL", "http://localhost:8000")
AGENT_ID  = os.environ.get("CREWLAYER_AGENT_ID", "")

if not API_KEY or not AGENT_ID:
    sys.exit("ERROR: Set CREWLAYER_API_KEY and CREWLAYER_AGENT_ID environment variables.")

# Check optional dependencies are installed
try:
    from langchain.chains import ConversationChain
    from langchain_openai import ChatOpenAI
except ImportError:
    sys.exit("ERROR: Run: pip install crewlayer[langchain] langchain langchain-openai")

if not os.environ.get("OPENAI_API_KEY"):
    sys.exit("ERROR: Set OPENAI_API_KEY environment variable.")

# ── Build CrewLayer client ────────────────────────────────────────────────────
client = CrewLayerClient(api_key=API_KEY, base_url=BASE_URL)

# ── Memory: persists the full conversation in CrewLayer's Redis store ─────────
# All messages (user + AI) are stored under session_id="demo-conversation".
# On the SECOND run the chain will load the existing history automatically.
memory = AgentLayerMemory(
    client=client,
    agent_id=AGENT_ID,
    session_id="demo-conversation",
    memory_key="history",
    return_messages=True,       # return ChatMessage objects (required by ChatOpenAI)
)

# ── Callback handler: logs every tool invocation as a CrewLayer action ────────
handler = AgentLayerCallbackHandler(
    client=client,
    agent_id=AGENT_ID,
    session_id="demo-conversation",
)

# ── Chain ─────────────────────────────────────────────────────────────────────
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
chain = ConversationChain(llm=llm, memory=memory, callbacks=[handler])

# ── Conversation turns ────────────────────────────────────────────────────────
print("─" * 60)
print("Starting conversation (session: demo-conversation)")
print("Run this script a second time — it will remember everything.")
print("─" * 60)

# Check how many messages are already stored from previous runs
existing = client.memory.messages(AGENT_ID, session_id="demo-conversation")
if existing.messages:
    print(f"\n[Memory] Found {len(existing.messages)} messages from a previous run.")
    for msg in existing.messages[-4:]:   # show last 4
        print(f"  {msg.role:>9}: {msg.content[:80]}")
    print()

turns = [
    "My name is Alex and I'm building an AI coding assistant.",
    "What programming languages should I focus on for AI?",
    "What did I tell you my name was?",   # tests if memory works across turns
]

for user_msg in turns:
    print(f"\nYou: {user_msg}")
    response = chain.predict(input=user_msg)
    print(f" AI: {response}")

# ── Show what was saved ───────────────────────────────────────────────────────
print("\n─" * 60)
updated = client.memory.messages(AGENT_ID, session_id="demo-conversation")
print(f"[Memory] Total messages stored: {updated.count}")

# ── Semantic recall: find memories about the user ─────────────────────────────
print("\n[Recall] Searching long-term memories about 'user profile'...")
client.memory.extract(AGENT_ID, "\n".join(
    f"{m.role}: {m.content}" for m in updated.messages
), session_id="demo-conversation")
recall = client.memory.recall(AGENT_ID, "user name and project", limit=3)
for item in recall.results:
    print(f"  [{item.similarity:.2f}] {item.content}")

client.close()
