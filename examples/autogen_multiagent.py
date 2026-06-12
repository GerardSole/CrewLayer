"""
AutoGen multi-agent workflow with shared CrewLayer blackboard.

Two agents collaborate on a task:
  - researcher: finds information and summarises it
  - writer: turns the summary into a polished paragraph

CrewLayerGroupChatManager writes every turn to the shared blackboard so any
external process can follow the conversation in real time without being in it.

After the chat, this script reads the blackboard and shows exactly what each
agent wrote and who spoke last.

Run:
    pip install crewlayer[autogen] pyautogen
    export CREWLAYER_API_KEY=crwl_...
    export CREWLAYER_RESEARCHER_AGENT_ID=<uuid>
    export CREWLAYER_WRITER_AGENT_ID=<uuid>
    export OPENAI_API_KEY=sk-...
    python examples/autogen_multiagent.py
"""
import os
import sys

from crewlayer import CrewLayerClient

API_KEY        = os.environ.get("CREWLAYER_API_KEY", "")
BASE_URL       = os.environ.get("CREWLAYER_URL", "http://localhost:8000")
RESEARCHER_ID  = os.environ.get("CREWLAYER_RESEARCHER_AGENT_ID", "")
WRITER_ID      = os.environ.get("CREWLAYER_WRITER_AGENT_ID", "")
OPENAI_KEY     = os.environ.get("OPENAI_API_KEY", "")

if not API_KEY or not RESEARCHER_ID or not WRITER_ID:
    sys.exit(
        "ERROR: Set CREWLAYER_API_KEY, CREWLAYER_RESEARCHER_AGENT_ID, "
        "and CREWLAYER_WRITER_AGENT_ID environment variables."
    )

try:
    import autogen
    from crewlayer.integrations.autogen import (
        CrewLayerAgentMemory,
        CrewLayerConversableAgent,
        CrewLayerGroupChatManager,
    )
except ImportError:
    sys.exit("ERROR: Run: pip install crewlayer[autogen] pyautogen")

if not OPENAI_KEY:
    sys.exit("ERROR: Set OPENAI_API_KEY environment variable.")

# ── CrewLayer client ──────────────────────────────────────────────────────────
client = CrewLayerClient(api_key=API_KEY, base_url=BASE_URL)

llm_config = {
    "config_list": [{"model": "gpt-4o-mini", "api_key": OPENAI_KEY}],
    "temperature": 0,
}

# ── Agents — each auto-persists every send/receive to CrewLayer memory ────────
researcher = CrewLayerConversableAgent(
    name="researcher",
    client=client,
    agent_id=RESEARCHER_ID,
    session_id="multiagent-demo",
    system_message=(
        "You are a research assistant. When given a topic, "
        "provide a concise 3-bullet summary of key facts. "
        "Keep your response under 100 words. Reply TERMINATE when done."
    ),
    llm_config=llm_config,
    human_input_mode="NEVER",
    max_consecutive_auto_reply=2,
)

writer = CrewLayerConversableAgent(
    name="writer",
    client=client,
    agent_id=WRITER_ID,
    session_id="multiagent-demo",
    system_message=(
        "You are a technical writer. Take the researcher's bullet points "
        "and rewrite them as one polished paragraph (max 80 words). "
        "Reply TERMINATE when done."
    ),
    llm_config=llm_config,
    human_input_mode="NEVER",
    max_consecutive_auto_reply=2,
)

# ── Load any long-term memories into each agent's system context ──────────────
# On the first run this is a no-op; on subsequent runs it enriches the agents
# with knowledge from previous sessions.
CrewLayerAgentMemory(client=client, agent_id=RESEARCHER_ID, limit=3).apply(researcher)
CrewLayerAgentMemory(client=client, agent_id=WRITER_ID, limit=3).apply(writer)

# ── GroupChat — manager writes every turn to the shared blackboard ─────────────
# Namespace "multiagent-demo" is readable by any process in real time:
#   client.context.read("multiagent-demo", "latest_turn")
groupchat = autogen.GroupChat(
    agents=[researcher, writer],
    messages=[],
    max_round=4,
    speaker_selection_method="round_robin",
)
manager = CrewLayerGroupChatManager(
    client=client,
    group_id="multiagent-demo",       # blackboard namespace
    groupchat=groupchat,
    llm_config=llm_config,
)

# ── Kick off the conversation ─────────────────────────────────────────────────
TOPIC = "the key benefits of using a shared memory backend for multi-agent AI systems"

print("─" * 65)
print(f"Topic: {TOPIC}")
print("─" * 65)

researcher.initiate_chat(
    manager,
    message=f"Research and summarise: {TOPIC}",
)

# ── Read the shared blackboard to see the final state ─────────────────────────
print("\n" + "─" * 65)
print("Blackboard state after the conversation (namespace: multiagent-demo)")
print("─" * 65)

try:
    latest = client.context.read("multiagent-demo", "latest_turn")
    v = latest.value
    print(f"  Last speaker : {v.get('agent', '?')}")
    print(f"  Turn         : {v.get('turn', '?')}")
    print(f"  Message      : {str(v.get('content', ''))[:120]}")
except Exception as exc:
    print(f"  (blackboard not written yet: {exc})")

# Per-agent last message
for name in ("researcher", "writer"):
    try:
        entry = client.context.read("multiagent-demo", f"agent:{name}")
        print(f"\n  agent:{name}")
        print(f"    turn    : {entry.value.get('turn', '?')}")
        print(f"    message : {str(entry.value.get('last_message', ''))[:120]}")
    except Exception:
        pass

# ── Action stats — how many calls each agent made ─────────────────────────────
print("\n─" * 65)
for agent_id, name in [(RESEARCHER_ID, "researcher"), (WRITER_ID, "writer")]:
    stats = client.actions.stats(agent_id)
    print(f"  {name}: {stats.total_actions} actions logged, "
          f"error rate {stats.error_rate:.0%}")

client.close()
print("\nDone.")
