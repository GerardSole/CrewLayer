"""
Agent response evaluation demo.

Demonstrates:
  - Logging 10 actions with varied scores (success, error, slow)
  - Submitting human evaluations (thumbs + score)
  - Creating an A/B test between two prompt versions
  - Simulating sessions assigned to each variant
  - Fetching A/B test results
  - Completing the test with a winner
  - Checking the evaluation summary and anomalies

Run:
    pip install crewlayer
    export CREWLAYER_API_KEY=crwl_...
    export CREWLAYER_AGENT_ID=<your-agent-uuid>
    python examples/evaluation.py
"""
import os
import random
import sys

from crewlayer import CrewLayerClient

API_KEY  = os.environ.get("CREWLAYER_API_KEY", "")
BASE_URL = os.environ.get("CREWLAYER_URL", "http://localhost:8000")
AGENT_ID = os.environ.get("CREWLAYER_AGENT_ID", "")

if not API_KEY or not AGENT_ID:
    sys.exit("ERROR: Set CREWLAYER_API_KEY and CREWLAYER_AGENT_ID environment variables.")

client = CrewLayerClient(api_key=API_KEY, base_url=BASE_URL)

# ── 1. Create two prompt versions for A/B test ────────────────────────────────
print("Creating two prompt versions...")
v1 = client.prompts.create(
    AGENT_ID,
    content="You are a concise assistant. Answer in 1-2 sentences.",
    description="Concise style",
)
v2 = client.prompts.create(
    AGENT_ID,
    content="You are a detailed assistant. Provide thorough explanations with examples.",
    description="Detailed style",
)
print(f"  v1: {v1.id} (version {v1.version})")
print(f"  v2: {v2.id} (version {v2.version})")

# ── 2. Create an A/B test ─────────────────────────────────────────────────────
print("\nCreating A/B test (50/50 split)...")
test = client.evaluations.create_ab_test(
    AGENT_ID,
    name="Concise vs Detailed prompt",
    variant_a_prompt_version_id=v1.id,
    variant_b_prompt_version_id=v2.id,
    traffic_split=0.5,
)
print(f"  Test id: {test.id}, status: {test.status}")

# ── 3. Log 10 actions with varied outcomes ────────────────────────────────────
print("\nLogging 10 actions with varied outcomes...")
statuses = ["success", "success", "success", "error", "success",
            "success", "error", "success", "success", "timeout"]
actions = []
for i, st in enumerate(statuses):
    action = client.actions.log(
        agent_id=AGENT_ID,
        tool_name="generate_response",
        input_params={"query": f"question {i+1}"},
        output_result={"answer": "..." * (50 if st == "success" else 1)},
        status=st,
        duration_ms=random.randint(200, 15_000),
        error_msg="LLM timeout" if st == "timeout" else None,
    )
    actions.append(action)
    print(f"  Action {i+1}: {action.id} ({st})")

# ── 4. Submit evaluations for successful actions ─────────────────────────────
print("\nSubmitting evaluations...")
scores = [4.5, 3.0, 5.0, None, 4.0, 2.5, None, 4.8, 3.5, None]
thumbs = ["up", "up", "up", None, "up", "down", None, "up", "up", None]
for action, score, thumb in zip(actions, scores, thumbs):
    if score is None and thumb is None:
        continue
    ev = client.evaluations.submit(
        AGENT_ID,
        action.id,
        rating_score=score,
        rating_thumbs=thumb,
        prompt_version_id=v1.id,
    )
    print(f"  Evaluated {action.id[:8]}...: score={score}, thumbs={thumb}")

# ── 5. Get evaluation summary ─────────────────────────────────────────────────
print("\nEvaluation summary:")
summary = client.evaluations.summary(AGENT_ID)
print(f"  Total evaluations: {summary.total_evaluations}")
print(f"  Average score: {summary.avg_score:.2f}" if summary.avg_score else "  Average score: N/A")
print(f"  Thumbs up: {summary.thumbs_up}, Thumbs down: {summary.thumbs_down}")
print(f"  Thumbs up ratio: {summary.thumbs_up_ratio:.0%}")

# ── 6. Check anomalies ────────────────────────────────────────────────────────
print("\nUnresolved anomalies:")
anomalies = client.evaluations.list_anomalies(AGENT_ID, resolved=False)
if anomalies:
    for a in anomalies:
        print(f"  [{a.severity.upper()}] {a.anomaly_type}: {a.details}")
    # Resolve all
    for a in anomalies:
        client.evaluations.resolve_anomaly(AGENT_ID, a.id)
    print(f"  Resolved {len(anomalies)} anomalies.")
else:
    print("  None detected.")

# ── 7. Get A/B test results and complete ──────────────────────────────────────
print("\nA/B test results:")
results = client.evaluations.get_ab_results(AGENT_ID, test.id)
for v in [results.variant_a, results.variant_b]:
    score_str = f"{v.avg_score:.2f}" if v.avg_score else "N/A"
    print(
        f"  Variant {v.variant}: {v.total_actions} actions, "
        f"error_rate={v.error_rate:.0%}, avg_score={score_str}, "
        f"thumbs_up={v.thumbs_up_ratio:.0%}"
    )

print("\nCompleting A/B test, declaring variant A the winner...")
completed = client.evaluations.complete_ab_test(AGENT_ID, test.id, winner="a")
print(f"  Status: {completed.status}, winner: {completed.winner}")

print("\nDone.")
client.close()
