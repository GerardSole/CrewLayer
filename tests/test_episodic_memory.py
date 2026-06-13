"""Episodic memory tests: create/list/detail, session linking, complete (AI summary), recall."""
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.db.models import EpisodeMemory, Memory

pytestmark = pytest.mark.asyncio

# Two orthogonal unit vectors for fake embeddings
_EMBED_A = [1.0] + [0.0] * 1535  # direction A
_EMBED_B = [0.0, 1.0] + [0.0] * 1534  # direction B (orthogonal to A, sim ≈ 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict]:
    r = await client.post("/v1/tenants", json={"name": f"EpCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    return tenant, {"X-API-Key": tenant["initial_api_key"]}


async def _create_agent(client: AsyncClient, headers: dict) -> dict:
    r = await client.post("/v1/agents", json={"name": f"bot-{uuid.uuid4()}"}, headers=headers)
    assert r.status_code == 201
    return r.json()


async def _create_session(client: AsyncClient, headers: dict, agent_id: str) -> dict:
    r = await client.post("/v1/sessions", json={"agent_id": agent_id}, headers=headers)
    assert r.status_code == 201
    return r.json()


async def _create_episode(client: AsyncClient, headers: dict, agent_id: str, title: str = "ep") -> dict:
    r = await client.post(
        f"/v1/agents/{agent_id}/episodes",
        json={"title": title, "description": "desc", "metadata": {"k": "v"}},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()


async def _seed_memory(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    content: str = "some memory",
    embedding: list[float] | None = None,
    created_at: datetime | None = None,
) -> Memory:
    kwargs: dict = dict(
        tenant_id=tenant_id,
        agent_id=agent_id,
        content=content,
        embedding=embedding or _EMBED_A,
        importance=0.5,
        base_importance=0.5,
        access_count=0,
        tags=[],
        merged_from=[],
    )
    if created_at is not None:
        kwargs["created_at"] = created_at
    mem = Memory(**kwargs)
    db.add(mem)
    await db.flush()
    return mem


# ---------------------------------------------------------------------------
# Episode CRUD
# ---------------------------------------------------------------------------

async def test_create_episode_returns_active(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    ep = await _create_episode(client, headers, agent["id"], title="My Task")

    assert ep["status"] == "active"
    assert ep["title"] == "My Task"
    assert ep["description"] == "desc"
    assert ep["metadata"] == {"k": "v"}
    assert ep["summary"] is None
    assert ep["completed_at"] is None
    assert ep["agent_id"] == agent["id"]


async def test_create_episode_unknown_agent_404(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    r = await client.post(
        f"/v1/agents/{uuid.uuid4()}/episodes",
        json={"title": "x"},
        headers=headers,
    )
    assert r.status_code == 404


async def test_list_episodes_returns_all(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    await _create_episode(client, headers, agent["id"], title="ep1")
    await _create_episode(client, headers, agent["id"], title="ep2")

    r = await client.get(f"/v1/agents/{agent['id']}/episodes", headers=headers)
    assert r.status_code == 200
    titles = {ep["title"] for ep in r.json()}
    assert titles == {"ep1", "ep2"}


async def test_list_episodes_filter_by_status(client: AsyncClient, mocker: pytest.MonkeyPatch) -> None:
    """Only completed episodes returned when ?status=completed."""
    mocker.patch("crewlayer.core.memory.episodic._client", new=MagicMock(
        messages=MagicMock(create=AsyncMock(return_value=MagicMock(
            content=[MagicMock(text="summary text")]
        )))
    ))
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    await _create_episode(client, headers, agent["id"], title="active-ep")
    ep2 = await _create_episode(client, headers, agent["id"], title="done-ep")

    await client.post(f"/v1/agents/{agent['id']}/episodes/{ep2['id']}/complete", headers=headers)

    r = await client.get(f"/v1/agents/{agent['id']}/episodes?status=active", headers=headers)
    assert r.status_code == 200
    titles = {ep["title"] for ep in r.json()}
    assert "active-ep" in titles
    assert "done-ep" not in titles

    r2 = await client.get(f"/v1/agents/{agent['id']}/episodes?status=completed", headers=headers)
    assert r2.status_code == 200
    titles2 = {ep["title"] for ep in r2.json()}
    assert "done-ep" in titles2


async def test_get_episode_detail_empty(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    ep = await _create_episode(client, headers, agent["id"])

    r = await client.get(f"/v1/agents/{agent['id']}/episodes/{ep['id']}", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == ep["id"]
    assert data["sessions"] == []
    assert data["memories"] == []


async def test_get_episode_404_for_unknown(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    r = await client.get(f"/v1/agents/{agent['id']}/episodes/{uuid.uuid4()}", headers=headers)
    assert r.status_code == 404


async def test_episode_tenant_isolation(client: AsyncClient) -> None:
    _, headers_a = await _setup(client)
    _, headers_b = await _setup(client)

    agent_a = await _create_agent(client, headers_a)
    ep = await _create_episode(client, headers_a, agent_a["id"])

    agent_b = await _create_agent(client, headers_b)
    r = await client.get(f"/v1/agents/{agent_b['id']}/episodes/{ep['id']}", headers=headers_b)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Session linking (PATCH /v1/sessions/{id})
# ---------------------------------------------------------------------------

async def test_patch_session_assigns_episode(client: AsyncClient, db: AsyncSession) -> None:
    tenant, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    ep = await _create_episode(client, headers, agent["id"])
    sess = await _create_session(client, headers, agent["id"])

    r = await client.patch(
        f"/v1/sessions/{sess['id']}",
        json={"episode_id": ep["id"]},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["episode_id"] == ep["id"]


async def test_patch_session_links_memories_in_time_window(
    client: AsyncClient, db: AsyncSession
) -> None:
    tenant, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    ep = await _create_episode(client, headers, agent["id"])
    sess = await _create_session(client, headers, agent["id"])

    # Seed a memory for this agent (created NOW = within session window)
    mem = await _seed_memory(
        db,
        tenant_id=uuid.UUID(tenant["id"]),
        agent_id=uuid.UUID(agent["id"]),
        content="memory during session",
    )
    await db.commit()

    # Link session to episode — should auto-discover the memory
    await client.patch(f"/v1/sessions/{sess['id']}", json={"episode_id": ep["id"]}, headers=headers)

    # Verify memory appears in episode detail
    r = await client.get(f"/v1/agents/{agent['id']}/episodes/{ep['id']}", headers=headers)
    mem_ids = {m["id"] for m in r.json()["memories"]}
    assert str(mem.id) in mem_ids


async def test_patch_session_clears_episode(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    ep = await _create_episode(client, headers, agent["id"])
    sess = await _create_session(client, headers, agent["id"])

    # Assign
    await client.patch(f"/v1/sessions/{sess['id']}", json={"episode_id": ep["id"]}, headers=headers)
    # Clear
    r = await client.patch(f"/v1/sessions/{sess['id']}", json={"episode_id": None}, headers=headers)
    assert r.status_code == 200
    assert r.json()["episode_id"] is None


async def test_patch_session_unknown_episode_404(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    sess = await _create_session(client, headers, agent["id"])

    r = await client.patch(
        f"/v1/sessions/{sess['id']}",
        json={"episode_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# complete_episode — AI summary generation
# ---------------------------------------------------------------------------

async def test_complete_episode_generates_summary(
    client: AsyncClient, db: AsyncSession, mocker: pytest.MonkeyPatch
) -> None:
    fake_summary = "Agent completed data analysis tasks successfully."
    mock_create = AsyncMock(return_value=MagicMock(content=[MagicMock(text=fake_summary)]))
    mocker.patch("crewlayer.core.memory.episodic._client", new=MagicMock(
        messages=MagicMock(create=mock_create)
    ))

    tenant, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    ep = await _create_episode(client, headers, agent["id"], title="Data Analysis")
    sess = await _create_session(client, headers, agent["id"])

    # Seed memory within session window
    await _seed_memory(
        db,
        tenant_id=uuid.UUID(tenant["id"]),
        agent_id=uuid.UUID(agent["id"]),
        content="Analyzed sales data for Q1",
    )
    await db.commit()

    # Link session to episode → auto-discovers memory
    await client.patch(f"/v1/sessions/{sess['id']}", json={"episode_id": ep["id"]}, headers=headers)

    # Complete the episode
    r = await client.post(
        f"/v1/agents/{agent['id']}/episodes/{ep['id']}/complete",
        headers=headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "completed"
    assert data["summary"] == fake_summary
    assert data["completed_at"] is not None
    mock_create.assert_called_once()


async def test_complete_episode_no_memories(
    client: AsyncClient, mocker: pytest.MonkeyPatch
) -> None:
    """Completing an episode with no memories still succeeds with a placeholder summary."""
    mocker.patch("crewlayer.core.memory.episodic._client", new=MagicMock(
        messages=MagicMock(create=AsyncMock())
    ))

    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    ep = await _create_episode(client, headers, agent["id"], title="Empty Episode")

    r = await client.post(
        f"/v1/agents/{agent['id']}/episodes/{ep['id']}/complete",
        headers=headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "completed"
    assert "Empty Episode" in data["summary"]
    # Claude not called (no memories)
    assert not mocker.patch("crewlayer.core.memory.episodic._client").messages.create.called


async def test_complete_episode_404_for_unknown(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    r = await client.post(
        f"/v1/agents/{agent['id']}/episodes/{uuid.uuid4()}/complete",
        headers=headers,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# recall_episode — semantic search within episode
# ---------------------------------------------------------------------------

async def test_recall_returns_only_episode_memories(
    client: AsyncClient, db: AsyncSession, mocker: pytest.MonkeyPatch
) -> None:
    """recall_episode must return memories from this episode only, not from others."""
    # Embed query → direction A (matches episode 1 memory, not episode 2)
    mocker.patch(
        "crewlayer.core.memory.episodic.get_embedding",
        new=AsyncMock(return_value=_EMBED_A),
    )

    tenant, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    ep1 = await _create_episode(client, headers, agent["id"], title="episode1")
    ep2 = await _create_episode(client, headers, agent["id"], title="episode2")

    # Seed two memories: one will belong to ep1, the other to ep2
    mem1 = await _seed_memory(db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]),
                               content="episode 1 content", embedding=_EMBED_A)
    mem2 = await _seed_memory(db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]),
                               content="episode 2 content", embedding=_EMBED_B)
    await db.commit()

    # Manually link memories to their respective episodes
    db.add(EpisodeMemory(episode_id=uuid.UUID(ep1["id"]), memory_id=mem1.id))
    db.add(EpisodeMemory(episode_id=uuid.UUID(ep2["id"]), memory_id=mem2.id))
    await db.commit()

    # Recall episode 1 only
    r = await client.post(
        f"/v1/agents/{agent['id']}/episodes/{ep1['id']}/recall",
        json={"query": "episode content", "limit": 10},
        headers=headers,
    )
    assert r.status_code == 200
    results = r.json()
    returned_ids = {res["memory_id"] for res in results}
    assert str(mem1.id) in returned_ids
    assert str(mem2.id) not in returned_ids


async def test_recall_empty_when_no_memories(
    client: AsyncClient, mocker: pytest.MonkeyPatch
) -> None:
    mocker.patch(
        "crewlayer.core.memory.episodic.get_embedding",
        new=AsyncMock(return_value=_EMBED_A),
    )
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    ep = await _create_episode(client, headers, agent["id"])

    r = await client.post(
        f"/v1/agents/{agent['id']}/episodes/{ep['id']}/recall",
        json={"query": "anything"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json() == []


async def test_recall_404_for_unknown_episode(
    client: AsyncClient, mocker: pytest.MonkeyPatch
) -> None:
    mocker.patch(
        "crewlayer.core.memory.episodic.get_embedding",
        new=AsyncMock(return_value=_EMBED_A),
    )
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    r = await client.post(
        f"/v1/agents/{agent['id']}/episodes/{uuid.uuid4()}/recall",
        json={"query": "x"},
        headers=headers,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET episode detail with sessions
# ---------------------------------------------------------------------------

async def test_episode_detail_shows_linked_session(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    ep = await _create_episode(client, headers, agent["id"])
    sess = await _create_session(client, headers, agent["id"])

    await client.patch(f"/v1/sessions/{sess['id']}", json={"episode_id": ep["id"]}, headers=headers)

    r = await client.get(f"/v1/agents/{agent['id']}/episodes/{ep['id']}", headers=headers)
    assert r.status_code == 200
    session_ids = {s["id"] for s in r.json()["sessions"]}
    assert sess["id"] in session_ids
