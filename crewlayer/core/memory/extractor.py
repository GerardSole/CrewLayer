import json
import uuid
from typing import Any, cast

import anthropic
from anthropic.types import TextBlock
from opentelemetry import trace

from crewlayer.core.memory.long import LongMemory

# Module-level client so tests can patch crewlayer.core.memory.extractor._client
_client = anthropic.AsyncAnthropic()
_tracer = trace.get_tracer("crewlayer.memory")

_SYSTEM = """\
You are a memory extraction assistant. Given a conversation, extract a list of
important facts and observations worth remembering long-term.

Respond ONLY with a JSON array (no markdown fences). Each element must have:
  - "content" (string): the fact to remember
  - "importance" (float 0.0–1.0): how important it is
  - "tags" (list[str]): relevant topic tags

Example:
[{"content": "User prefers Python", "importance": 0.8, "tags": ["preferences"]}]
"""


_MODEL = "claude-opus-4-8"


async def extract_and_save(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    conversation: str,
    long_memory: LongMemory,
    *,
    session_id: str | None = None,
) -> list[uuid.UUID]:
    """Call claude-opus-4-8 to extract facts from a conversation and persist them.

    Returns the list of newly created Memory IDs.
    """
    with _tracer.start_as_current_span("memory.extract") as span:
        span.set_attribute("tenant_id", str(tenant_id))
        span.set_attribute("agent_id", str(agent_id))
        span.set_attribute("model_used", _MODEL)
        if session_id is not None:
            span.set_attribute("session_id", str(session_id))

        response = await _client.messages.create(
            model=_MODEL,
            max_tokens=2048,
            system=_SYSTEM,
            messages=[{"role": "user", "content": conversation}],
        )
        raw = cast(TextBlock, response.content[0]).text.strip()

        # Strip markdown code fences when the model ignores the system prompt
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0].strip()

        try:
            facts: list[dict[str, Any]] = json.loads(raw)
        except json.JSONDecodeError:
            span.set_attribute("memories_extracted", 0)
            return []

        saved_ids: list[uuid.UUID] = []
        for fact in facts:
            if not isinstance(fact, dict) or "content" not in fact:
                continue
            memory = await long_memory.save(
                tenant_id=tenant_id,
                agent_id=agent_id,
                content=str(fact["content"]),
                importance=float(fact.get("importance", 0.5)),
                tags=list(fact.get("tags", [])),
            )
            saved_ids.append(memory.id)

        span.set_attribute("memories_extracted", len(saved_ids))
        return saved_ids
