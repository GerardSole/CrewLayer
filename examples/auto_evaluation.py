"""
LLM-as-a-judge auto-evaluation demo.

Demonstrates:
  - Logging 5 actions with varied statuses
  - Auto-evaluating a single action via Claude
  - Batch auto-evaluating all pending actions
  - Fetching the evaluation summary with criteria averages

Run:
    pip install crewlayer
    export CREWLAYER_API_KEY=crwl_...
    export CREWLAYER_AGENT_ID=<your-agent-uuid>
    python examples/auto_evaluation.py
"""
import os
import time

from crewlayer import CrewLayerClient

API_KEY = os.environ["CREWLAYER_API_KEY"]
AGENT_ID = os.environ["CREWLAYER_AGENT_ID"]

client = CrewLayerClient(api_key=API_KEY)

# ── 1. Log a few actions ──────────────────────────────────────────────────────

print("Logging 5 sample actions…")

actions = []
samples = [
    ("search_web", {"query": "latest AI research"}, {"results": ["paper1", "paper2"]}, "success", 320),
    ("summarize", {"text": "Long document…"}, {"summary": "Brief summary."}, "success", 1100),
    ("send_email", {"to": "user@example.com"}, None, "error", None),
    ("run_code", {"code": "print(42)"}, {"output": "42"}, "success", 88),
    ("fetch_data", {"url": "https://api.example.com/data"}, {"rows": 100}, "success", 450),
]

for tool_name, input_params, output_result, status, duration_ms in samples:
    action = client.actions.log(
        AGENT_ID,
        tool_name=tool_name,
        input_params=input_params,
        output_result=output_result or {},
        status=status,
        duration_ms=duration_ms or 0,
    )
    actions.append(action)
    print(f"  logged {tool_name} → {action.id} ({status})")

# ── 2. Auto-evaluate a single action ─────────────────────────────────────────

print("\nAuto-evaluating first action via Claude…")
result = client.evaluations.auto_evaluate(
    AGENT_ID,
    actions[0].id,
    criteria=["correctness", "efficiency", "completeness", "safety"],
)
print(f"  Score:    {result.score:.2f} / 5.0  ({result.thumbs})")
print(f"  Reasoning: {result.reasoning}")
print("  Criteria:")
for criterion, score in result.criteria_scores.items():
    bar = "█" * int(score) + "░" * (5 - int(score))
    print(f"    {criterion:<15} {bar} {score:.1f}")

# ── 3. Batch auto-evaluate all remaining actions ──────────────────────────────

print("\nStarting batch auto-evaluation (background job)…")
batch = client.evaluations.auto_evaluate_batch(AGENT_ID, limit=50)
print(f"  job_started:     {batch.job_started}")
print(f"  actions_pending: {batch.actions_pending}")
print("  (Evaluation runs asynchronously — check the summary in a few seconds)")

# ── 4. Wait and check the summary ────────────────────────────────────────────

print("\nWaiting 5 s for background evaluations to complete…")
time.sleep(5)

summary = client.evaluations.summary(AGENT_ID)
print(f"\nEvaluation Summary for agent {AGENT_ID}:")
print(f"  Total:    {summary.total_evaluations}")
print(f"  Auto:     {summary.auto_evaluated_count}")
print(f"  Human:    {summary.human_evaluated_count}")
print(f"  Avg score: {summary.avg_score:.2f}" if summary.avg_score else "  Avg score: N/A")
print(f"  Thumbs 👍 {summary.thumbs_up}  👎 {summary.thumbs_down}")

if summary.criteria_averages:
    print("\n  Criteria averages:")
    for criterion, avg in summary.criteria_averages.items():
        bar = "█" * int(avg) + "░" * (5 - int(avg))
        print(f"    {criterion:<15} {bar} {avg:.2f}")
