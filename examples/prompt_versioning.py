"""
Prompt version control demo.

Demonstrates:
  - Creating three versions of an agent system prompt
  - Activating the second version
  - Simulating poor performance (logging actions with error status)
  - Rolling back to the first version
  - Showing a diff between two versions

Run:
    pip install crewlayer
    export CREWLAYER_API_KEY=crwl_...
    export CREWLAYER_AGENT_ID=<your-agent-uuid>
    python examples/prompt_versioning.py
"""
import os
import sys

from crewlayer import CrewLayerClient

API_KEY  = os.environ.get("CREWLAYER_API_KEY", "")
BASE_URL = os.environ.get("CREWLAYER_URL", "http://localhost:8000")
AGENT_ID = os.environ.get("CREWLAYER_AGENT_ID", "")

if not API_KEY or not AGENT_ID:
    sys.exit("ERROR: Set CREWLAYER_API_KEY and CREWLAYER_AGENT_ID environment variables.")

client = CrewLayerClient(api_key=API_KEY, base_url=BASE_URL)

print("─" * 60)
print("CrewLayer — Prompt Version Control Demo")
print("─" * 60)

# ── Step 1: Create three prompt versions ─────────────────────────────────────
print("\n[1] Creating three prompt versions...")

v1 = client.prompts.create(
    AGENT_ID,
    content=(
        "You are a helpful assistant.\n"
        "Answer questions clearly and concisely.\n"
        "Always be polite."
    ),
    description="v1 — base prompt, concise and polite",
)
print(f"  ✓ Version {v1.version} created  (id: {v1.id})")

v2 = client.prompts.create(
    AGENT_ID,
    content=(
        "You are an expert assistant with deep knowledge.\n"
        "Provide detailed, comprehensive answers.\n"
        "Include examples whenever possible.\n"
        "Always be polite and professional."
    ),
    description="v2 — verbose, with examples",
)
print(f"  ✓ Version {v2.version} created  (id: {v2.id})")

v3 = client.prompts.create(
    AGENT_ID,
    content=(
        "You are an expert assistant.\n"
        "Be extremely brief. One sentence max per answer.\n"
        "No pleasantries."
    ),
    description="v3 — ultra-terse (experimental)",
)
print(f"  ✓ Version {v3.version} created  (id: {v3.id})")

# ── Step 2: List all versions ─────────────────────────────────────────────────
print(f"\n[2] All versions for agent ({AGENT_ID[:8]}…):")
page = client.prompts.list(AGENT_ID)
for pv in page.items:
    flag = " ← active" if pv.is_active else ""
    print(f"    v{pv.version}  {'[ACTIVE]' if pv.is_active else '        '}  {pv.description}{flag}")

# ── Step 3: Activate version 2 ────────────────────────────────────────────────
print(f"\n[3] Activating version {v2.version}...")
active = client.prompts.activate(AGENT_ID, v2.id)
print(f"  ✓ Version {active.version} is now active")

# ── Step 4: Confirm via get_active ────────────────────────────────────────────
current = client.prompts.get_active(AGENT_ID)
print(f"\n[4] Active prompt content preview:\n    {current.content[:80].replace(chr(10), ' | ')}")

# ── Step 5: Simulate poor performance ─────────────────────────────────────────
print("\n[5] Simulating three failed actions with v2 active (prompt too verbose)...")
for i in range(3):
    client.actions.log(
        AGENT_ID,
        tool_name="llm_call",
        input_params={"prompt_version": v2.version},
        output_result={"error": "Response too long, context window exceeded"},
        status="error",
        error_msg="Token limit exceeded",
        metadata={"prompt_version_id": v2.id},
    )
print("  ✓ 3 error actions logged")

# ── Step 6: Rollback to version 1 ─────────────────────────────────────────────
print("\n[6] Rolling back to the previous version...")
rolled_back = client.prompts.rollback(AGENT_ID)
print(f"  ✓ Rolled back to version {rolled_back.version}: '{rolled_back.description}'")

# ── Step 7: Show diff between v1 and v2 ──────────────────────────────────────
print(f"\n[7] Diff between v{v1.version} and v{v2.version}:")
result = client.prompts.diff(AGENT_ID, v1.id, v2.id)
for line in result.lines:
    if line.operation == "equal":
        print(f"    = {line.content}")
    elif line.operation == "insert":
        print(f"  + {line.content}")
    elif line.operation == "delete":
        print(f"  - {line.content}")

# ── Step 8: Confirm final state ───────────────────────────────────────────────
print("\n[8] Final state:")
page = client.prompts.list(AGENT_ID)
for pv in page.items:
    status = "ACTIVE" if pv.is_active else "      "
    print(f"    v{pv.version}  [{status}]  {pv.description}")

print("\n─" * 60)
print("Done! Prompt version control is working correctly.")
print("─" * 60)

client.close()
