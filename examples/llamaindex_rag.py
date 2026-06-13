"""
LlamaIndex RAG — index documents and query them with CrewLayer.

Demonstrates:
  - CrewLayerVectorIndex: insert documents → stored as long-term memories via pgvector
  - CrewLayerQueryEngine: semantic queries with automatic action logging
  - Direct similarity_search for retrieving raw MemoryItem results

Every query is logged as a "llamaindex.query" action in CrewLayer's audit trail.
Run this script twice: the second run will query documents indexed in the first run.

Run:
    pip install crewlayer[llamaindex] llama-index-core
    export CREWLAYER_API_KEY=crwl_...
    export CREWLAYER_AGENT_ID=<your-agent-uuid>
    python examples/llamaindex_rag.py
"""
import os
import sys
import time

from crewlayer import CrewLayerClient

API_KEY   = os.environ.get("CREWLAYER_API_KEY", "")
BASE_URL  = os.environ.get("CREWLAYER_URL", "http://localhost:8000")
AGENT_ID  = os.environ.get("CREWLAYER_AGENT_ID", "")

if not API_KEY or not AGENT_ID:
    sys.exit("ERROR: Set CREWLAYER_API_KEY and CREWLAYER_AGENT_ID environment variables.")

try:
    from crewlayer.integrations.llamaindex import CrewLayerVectorIndex
    from llama_index.core.schema import Document
except ImportError:
    sys.exit("ERROR: Run: pip install crewlayer[llamaindex] llama-index-core")

# ── Build CrewLayer client ────────────────────────────────────────────────────
client = CrewLayerClient(api_key=API_KEY, base_url=BASE_URL)

# ── Source documents ──────────────────────────────────────────────────────────
documents = [
    Document(
        text=(
            "CrewLayer provides persistent memory for AI agents. "
            "It stores both short-term session messages in Redis and "
            "long-term semantic memories in PostgreSQL with pgvector embeddings."
        ),
        metadata={"source": "crewlayer-docs", "section": "overview"},
    ),
    Document(
        text=(
            "The blackboard (context) API lets multiple agents share state "
            "in real time. Keys support optimistic locking via expected_version "
            "to prevent concurrent write conflicts."
        ),
        metadata={"source": "crewlayer-docs", "section": "blackboard"},
    ),
    Document(
        text=(
            "CrewLayer integrates natively with LangChain, LlamaIndex, AutoGen, "
            "and the Vercel AI SDK. Each integration is installed as an optional extra: "
            "pip install crewlayer[langchain] or crewlayer[autogen]."
        ),
        metadata={"source": "crewlayer-docs", "section": "integrations"},
    ),
]

# ── Build the index ───────────────────────────────────────────────────────────
# similarity_top_k controls how many memories the query engine returns.
index = CrewLayerVectorIndex(
    client=client,
    agent_id=AGENT_ID,
    similarity_top_k=3,
    min_similarity=0.4,
)

# ── Index documents (idempotent — re-running just adds more memories) ─────────
print("Indexing documents...")
for doc in documents:
    index.insert(doc)
    print(f"  ✓ Indexed: {doc.text[:60]}...")

# CrewLayer's extraction is async; give it a moment before querying
time.sleep(1)

# ── Build a query engine (each query is logged as a CrewLayer action) ─────────
engine = index.as_query_engine(session_id="rag-demo")

# ── Run semantic queries ──────────────────────────────────────────────────────
queries = [
    "How does CrewLayer store agent memory?",
    "How do multiple agents share state?",
    "Which AI frameworks does CrewLayer support?",
]

print("\n" + "─" * 65)
print("Running semantic queries")
print("─" * 65)

for query in queries:
    print(f"\nQ: {query}")
    start = time.monotonic()
    response = engine.query(query)
    elapsed = int((time.monotonic() - start) * 1000)

    print(f"A: {response.response[:200]}")
    print(f"   ({len(response.source_nodes)} source nodes, {elapsed}ms)")

# ── Direct similarity_search — get raw MemoryItem results ────────────────────
print("\n" + "─" * 65)
print("Direct similarity_search (raw MemoryItem results)")
print("─" * 65)

items = index.similarity_search("blackboard optimistic locking", top_k=2)
for item in items:
    print(f"  [{item.similarity:.2f}] {item.content[:100]}")

# ── Action stats — see how many queries were logged ───────────────────────────
print("\n─" * 65)
stats = client.actions.stats(AGENT_ID)
print(f"Total actions logged for this agent: {stats.total_actions}")
for tool in stats.by_tool:
    print(f"  {tool.tool_name}: {tool.count} calls")

client.close()
print("\nDone.")
