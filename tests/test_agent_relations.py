"""Agent hierarchy and relation tests: CRUD, validation, tree, blackboard propagation."""
import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict]:
    r = await client.post("/v1/tenants", json={"name": f"RelCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    return tenant, {"X-API-Key": tenant["initial_api_key"]}


async def _create_agent(client: AsyncClient, headers: dict, name: str | None = None) -> dict:
    r = await client.post(
        "/v1/agents",
        json={"name": name or f"agent-{uuid.uuid4()}"},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()


async def _set_relation(
    client: AsyncClient,
    headers: dict,
    agent_id: str,
    other_id: str,
    relation_type: str,
) -> dict:
    r = await client.post(
        f"/v1/agents/{agent_id}/relations",
        json={"other_agent_id": other_id, "relation_type": relation_type},
        headers=headers,
    )
    return r


# ---------------------------------------------------------------------------
# Supervisor relation CRUD
# ---------------------------------------------------------------------------

async def test_create_supervisor_relation(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    sup = await _create_agent(client, headers, "supervisor")
    sub = await _create_agent(client, headers, "subordinate")

    r = await _set_relation(client, headers, sup["id"], sub["id"], "supervisor")
    assert r.status_code == 201
    data = r.json()
    assert data["supervisor_id"] == sup["id"]
    assert data["subordinate_id"] == sub["id"]
    assert data["relation_type"] == "supervisor"


async def test_create_collaborator_relation(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    a = await _create_agent(client, headers)
    b = await _create_agent(client, headers)

    r = await _set_relation(client, headers, a["id"], b["id"], "collaborator")
    assert r.status_code == 201
    assert r.json()["relation_type"] == "collaborator"


async def test_create_delegate_relation(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    a = await _create_agent(client, headers)
    b = await _create_agent(client, headers)

    r = await _set_relation(client, headers, a["id"], b["id"], "delegate")
    assert r.status_code == 201
    assert r.json()["relation_type"] == "delegate"


async def test_list_relations_returns_all(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    sup = await _create_agent(client, headers)
    sub1 = await _create_agent(client, headers)
    sub2 = await _create_agent(client, headers)

    await _set_relation(client, headers, sup["id"], sub1["id"], "supervisor")
    await _set_relation(client, headers, sup["id"], sub2["id"], "collaborator")

    r = await client.get(f"/v1/agents/{sup['id']}/relations", headers=headers)
    assert r.status_code == 200
    ids = {(rel["supervisor_id"], rel["subordinate_id"]) for rel in r.json()}
    assert (sup["id"], sub1["id"]) in ids
    assert (sup["id"], sub2["id"]) in ids


async def test_list_relations_shows_from_both_sides(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    sup = await _create_agent(client, headers)
    sub = await _create_agent(client, headers)

    await _set_relation(client, headers, sup["id"], sub["id"], "supervisor")

    # Relations for the subordinate should also include the relation
    r = await client.get(f"/v1/agents/{sub['id']}/relations", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 1


async def test_delete_relation(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    sup = await _create_agent(client, headers)
    sub = await _create_agent(client, headers)

    await _set_relation(client, headers, sup["id"], sub["id"], "supervisor")

    r = await client.delete(
        f"/v1/agents/{sup['id']}/relations/{sub['id']}", headers=headers
    )
    assert r.status_code == 204

    # Verify it's gone
    r2 = await client.get(f"/v1/agents/{sup['id']}/relations", headers=headers)
    assert r2.json() == []


async def test_delete_nonexistent_relation_404(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    a = await _create_agent(client, headers)
    b = await _create_agent(client, headers)

    r = await client.delete(
        f"/v1/agents/{a['id']}/relations/{b['id']}", headers=headers
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

async def test_self_relation_rejected(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    r = await _set_relation(client, headers, agent["id"], agent["id"], "supervisor")
    assert r.status_code == 422


async def test_cycle_rejected(client: AsyncClient) -> None:
    """A → supervises → B; B → supervises → A must be rejected."""
    _, headers = await _setup(client)
    a = await _create_agent(client, headers)
    b = await _create_agent(client, headers)

    r1 = await _set_relation(client, headers, a["id"], b["id"], "supervisor")
    assert r1.status_code == 201

    r2 = await _set_relation(client, headers, b["id"], a["id"], "supervisor")
    assert r2.status_code == 422
    assert "ciclo" in r2.json()["detail"].lower()


async def test_transitive_cycle_rejected(client: AsyncClient) -> None:
    """A→B→C; C→A must be rejected (transitive cycle)."""
    _, headers = await _setup(client)
    a = await _create_agent(client, headers)
    b = await _create_agent(client, headers)
    c = await _create_agent(client, headers)

    await _set_relation(client, headers, a["id"], b["id"], "supervisor")
    await _set_relation(client, headers, b["id"], c["id"], "supervisor")

    r = await _set_relation(client, headers, c["id"], a["id"], "supervisor")
    assert r.status_code == 422


async def test_duplicate_supervisor_rejected(client: AsyncClient) -> None:
    """An agent can only have one supervisor."""
    _, headers = await _setup(client)
    sup1 = await _create_agent(client, headers)
    sup2 = await _create_agent(client, headers)
    sub = await _create_agent(client, headers)

    await _set_relation(client, headers, sup1["id"], sub["id"], "supervisor")

    r = await _set_relation(client, headers, sup2["id"], sub["id"], "supervisor")
    assert r.status_code == 422
    assert "supervisor" in r.json()["detail"].lower()


async def test_unknown_agent_returns_404(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    r = await _set_relation(client, headers, agent["id"], str(uuid.uuid4()), "supervisor")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Hierarchy tree
# ---------------------------------------------------------------------------

async def test_tree_single_level(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    sup = await _create_agent(client, headers, "root")
    sub1 = await _create_agent(client, headers, "child1")
    sub2 = await _create_agent(client, headers, "child2")

    await _set_relation(client, headers, sup["id"], sub1["id"], "supervisor")
    await _set_relation(client, headers, sup["id"], sub2["id"], "supervisor")

    r = await client.get(f"/v1/agents/{sup['id']}/tree", headers=headers)
    assert r.status_code == 200
    tree = r.json()
    assert tree["id"] == sup["id"]
    assert tree["name"] == "root"
    child_ids = {c["id"] for c in tree["subordinates"]}
    assert sub1["id"] in child_ids
    assert sub2["id"] in child_ids


async def test_tree_multi_level(client: AsyncClient) -> None:
    """A→B→C — tree should be 3 levels deep."""
    _, headers = await _setup(client)
    a = await _create_agent(client, headers, "A")
    b = await _create_agent(client, headers, "B")
    c = await _create_agent(client, headers, "C")

    await _set_relation(client, headers, a["id"], b["id"], "supervisor")
    await _set_relation(client, headers, b["id"], c["id"], "supervisor")

    r = await client.get(f"/v1/agents/{a['id']}/tree", headers=headers)
    assert r.status_code == 200
    tree = r.json()
    assert tree["id"] == a["id"]
    assert len(tree["subordinates"]) == 1
    b_node = tree["subordinates"][0]
    assert b_node["id"] == b["id"]
    assert len(b_node["subordinates"]) == 1
    assert b_node["subordinates"][0]["id"] == c["id"]


async def test_tree_leaf_has_no_subordinates(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    r = await client.get(f"/v1/agents/{agent['id']}/tree", headers=headers)
    assert r.status_code == 200
    assert r.json()["subordinates"] == []


async def test_tree_unknown_agent_404(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    r = await client.get(f"/v1/agents/{uuid.uuid4()}/tree", headers=headers)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Blackboard propagation
# ---------------------------------------------------------------------------

async def test_propagate_writes_to_subordinate_namespace(client: AsyncClient) -> None:
    """When propagate=True, the value is written to namespace=str(subordinate_id)."""
    _, headers = await _setup(client)
    sup = await _create_agent(client, headers)
    sub = await _create_agent(client, headers)

    await _set_relation(client, headers, sup["id"], sub["id"], "supervisor")

    # Write with propagate=True from supervisor
    r = await client.put(
        f"/v1/context/{sup['id']}/broadcast",
        json={"value": {"msg": "hello"}, "written_by": sup["id"], "propagate": True},
        headers=headers,
    )
    assert r.status_code == 200

    # Subordinate's namespace should have the value
    r2 = await client.get(f"/v1/context/{sub['id']}/broadcast", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["value"] == {"msg": "hello"}


async def test_propagate_false_does_not_write_to_subordinate(client: AsyncClient) -> None:
    """Without propagate, subordinate's namespace is unchanged."""
    _, headers = await _setup(client)
    sup = await _create_agent(client, headers)
    sub = await _create_agent(client, headers)

    await _set_relation(client, headers, sup["id"], sub["id"], "supervisor")

    await client.put(
        f"/v1/context/{sup['id']}/broadcast",
        json={"value": {"msg": "noprop"}, "written_by": sup["id"], "propagate": False},
        headers=headers,
    )

    r = await client.get(f"/v1/context/{sub['id']}/broadcast", headers=headers)
    assert r.status_code == 404


async def test_propagate_only_to_supervisor_type_subordinates(client: AsyncClient) -> None:
    """Collaborator-type relations are NOT propagated to."""
    _, headers = await _setup(client)
    a = await _create_agent(client, headers)
    b = await _create_agent(client, headers)

    await _set_relation(client, headers, a["id"], b["id"], "collaborator")

    await client.put(
        f"/v1/context/{a['id']}/msg",
        json={"value": {"x": 1}, "written_by": a["id"], "propagate": True},
        headers=headers,
    )

    r = await client.get(f"/v1/context/{b['id']}/msg", headers=headers)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

async def test_tenant_isolation_cannot_see_other_tenant_relations(
    client: AsyncClient,
) -> None:
    _, headers_a = await _setup(client)
    _, headers_b = await _setup(client)

    sup = await _create_agent(client, headers_a)
    sub = await _create_agent(client, headers_a)
    await _set_relation(client, headers_a, sup["id"], sub["id"], "supervisor")

    # Tenant B queries the tree for tenant A's agent → 404 (not found in B's tenant)
    r = await client.get(f"/v1/agents/{sup['id']}/tree", headers=headers_b)
    assert r.status_code == 404


async def test_tenant_isolation_cannot_set_cross_tenant_relation(
    client: AsyncClient,
) -> None:
    _, headers_a = await _setup(client)
    _, headers_b = await _setup(client)

    agent_a = await _create_agent(client, headers_a)
    agent_b = await _create_agent(client, headers_b)

    r = await _set_relation(client, headers_a, agent_a["id"], agent_b["id"], "supervisor")
    assert r.status_code == 404
