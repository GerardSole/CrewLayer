"""
CrewLayer quickstart — the simplest possible example.

Shows the four core primitives in under 30 lines:
  1. Short-term memory  (append)
  2. Long-term recall   (semantic search)
  3. Action log         (immutable audit trail)
  4. Shared blackboard  (context read/write)

Run:
    pip install crewlayer
    export CREWLAYER_API_KEY=crwl_...
    export CREWLAYER_AGENT_ID=<your-agent-uuid>
    python examples/quickstart.py
"""
import os
import sys

from crewlayer import CrewLayerClient

API_KEY   = os.environ.get("CREWLAYER_API_KEY", "")
BASE_URL  = os.environ.get("CREWLAYER_URL", "http://localhost:8000")
AGENT_ID  = os.environ.get("CREWLAYER_AGENT_ID", "")

if not API_KEY or not AGENT_ID:
    sys.exit("ERROR: Set CREWLAYER_API_KEY and CREWLAYER_AGENT_ID environment variables.")

client = CrewLayerClient(api_key=API_KEY, base_url=BASE_URL)

# ── 1. Store three facts in long-term memory ──────────────────────────────────
print("Saving memories...")
facts = [
    "The user prefers Python over JavaScript",
    "The user is building a multi-agent RAG pipeline",
    "The user wants responses in Spanish",
]
for fact in facts:
    client.memory.extract(AGENT_ID, fact)
    print(f"  ✓ {fact}")

# ── 2. Semantic recall — finds the most relevant memories ────────────────────
print("\nRecalling memories about 'programming language'...")
results = client.memory.recall(AGENT_ID, "programming language preferences", limit=3)
for item in results.results:
    print(f"  [{item.similarity:.2f}] {item.content}")

# ── 3. Log an action (immutable audit entry) ─────────────────────────────────
print("\nLogging action...")
action = client.actions.log(
    AGENT_ID,
    tool_name="quickstart_demo",
    input_params={"query": "programming language"},
    output_result={"memories_found": len(results.results)},
    status="success",
    duration_ms=42,
)
print(f"  ✓ Action logged: {action.id}")

# ── 4. Shared blackboard (context) ───────────────────────────────────────────
print("\nWriting to blackboard...")
entry = client.context.write(
    namespace="quickstart-demo",
    key="status",
    value={"phase": "done", "memories": len(results.results)},
    written_by=AGENT_ID,
)
print(f"  ✓ Written (version {entry.version})")

read_back = client.context.read("quickstart-demo", "status")
print(f"  ✓ Read back: {read_back.value}")

client.close()
print("\nAll done! CrewLayer is working correctly.")
