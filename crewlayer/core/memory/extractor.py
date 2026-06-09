import json
import uuid

import anthropic

from crewlayer.core.memory.long import LongMemory

# Module-level client so tests can patch crewlayer.core.memory.extractor._client
_client = anthropic.AsyncAnthropic()

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


async def extract_and_save(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    conversation: str,
    long_memory: LongMemory,
) -> list[uuid.UUID]:
    """Call claude-opus-4-8 to extract facts from a conversation and persist them.

    Returns the list of newly created Memory IDs.
    """
    response = await _client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2048,
        system=_SYSTEM,
        messages=[{"role": "user", "content": conversation}],
    )
    raw = response.content[0].text.strip()

    # Strip markdown code fences when the model ignores the system prompt
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0].strip()

    try:
        facts: list[dict] = json.loads(raw)
    except json.JSONDecodeError:
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

    return saved_ids
