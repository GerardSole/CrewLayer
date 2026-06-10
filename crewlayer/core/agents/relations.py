import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.db.models import Agent, AgentRelation, AgentRelationTypeEnum


class AgentRelationError(Exception):
    pass


class SelfRelationError(AgentRelationError):
    pass


class CycleError(AgentRelationError):
    pass


class DuplicateSupervisorError(AgentRelationError):
    pass


class RelationNotFoundError(AgentRelationError):
    pass


class AgentNotFoundError(AgentRelationError):
    pass


class AgentRelations:
    """Manages hierarchical and peer relationships between agents within a tenant."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def set_relation(
        self,
        tenant_id: uuid.UUID,
        supervisor_id: uuid.UUID,
        subordinate_id: uuid.UUID,
        relation_type: AgentRelationTypeEnum,
    ) -> AgentRelation:
        """Create or update a relation between two agents.

        For supervisor type:
        - Rejects self-relations.
        - Rejects if subordinate already has a different supervisor.
        - Rejects if the new relation would create a cycle.
        An agent may only have one supervisor but multiple collaborators/delegates.
        """
        if supervisor_id == subordinate_id:
            raise SelfRelationError("An agent cannot relate to itself")

        await self._load_agent(supervisor_id, tenant_id)
        await self._load_agent(subordinate_id, tenant_id)

        if relation_type == AgentRelationTypeEnum.supervisor:
            existing_sup = await self.get_supervisor(tenant_id, subordinate_id)
            if existing_sup is not None and existing_sup.supervisor_id != supervisor_id:
                raise DuplicateSupervisorError(
                    f"Agent {subordinate_id} already has supervisor {existing_sup.supervisor_id}"
                )
            if await self._has_supervisor_path(tenant_id, subordinate_id, supervisor_id):
                raise CycleError(
                    f"Cycle: {subordinate_id} already supervises {supervisor_id}"
                )

        existing = await self._get_relation(tenant_id, supervisor_id, subordinate_id)
        if existing is not None:
            existing.relation_type = relation_type
            rel = existing
        else:
            rel = AgentRelation(
                tenant_id=tenant_id,
                supervisor_id=supervisor_id,
                subordinate_id=subordinate_id,
                relation_type=relation_type,
            )
            self._db.add(rel)

        await self._db.flush()
        return rel

    async def get_subordinates(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        *,
        relation_type: AgentRelationTypeEnum | None = None,
    ) -> list[AgentRelation]:
        """Return all relations where agent_id is the supervisor."""
        stmt = select(AgentRelation).where(
            AgentRelation.tenant_id == tenant_id,
            AgentRelation.supervisor_id == agent_id,
        )
        if relation_type is not None:
            stmt = stmt.where(AgentRelation.relation_type == relation_type)
        return list((await self._db.execute(stmt)).scalars().all())

    async def get_supervisor(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> AgentRelation | None:
        """Return the supervisor relation for agent_id, or None if it has none."""
        return (await self._db.execute(
            select(AgentRelation).where(
                AgentRelation.tenant_id == tenant_id,
                AgentRelation.subordinate_id == agent_id,
                AgentRelation.relation_type == AgentRelationTypeEnum.supervisor,
            )
        )).scalar_one_or_none()

    async def get_collaborators(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> list[AgentRelation]:
        """Return all collaborator relations involving agent_id (either side)."""
        return list((await self._db.execute(
            select(AgentRelation).where(
                AgentRelation.tenant_id == tenant_id,
                AgentRelation.relation_type == AgentRelationTypeEnum.collaborator,
                or_(
                    AgentRelation.supervisor_id == agent_id,
                    AgentRelation.subordinate_id == agent_id,
                ),
            )
        )).scalars().all())

    async def get_all_relations(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> list[AgentRelation]:
        """Return every relation where agent_id appears on either side."""
        return list((await self._db.execute(
            select(AgentRelation).where(
                AgentRelation.tenant_id == tenant_id,
                or_(
                    AgentRelation.supervisor_id == agent_id,
                    AgentRelation.subordinate_id == agent_id,
                ),
            ).order_by(AgentRelation.created_at)
        )).scalars().all())

    async def delete_relation(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        other_agent_id: uuid.UUID,
    ) -> bool:
        """Delete the relation between agent_id and other_agent_id in either direction."""
        rel = (await self._db.execute(
            select(AgentRelation).where(
                AgentRelation.tenant_id == tenant_id,
                or_(
                    (AgentRelation.supervisor_id == agent_id)
                    & (AgentRelation.subordinate_id == other_agent_id),
                    (AgentRelation.supervisor_id == other_agent_id)
                    & (AgentRelation.subordinate_id == agent_id),
                ),
            )
        )).scalar_one_or_none()
        if rel is None:
            return False
        await self._db.delete(rel)
        await self._db.flush()
        return True

    async def get_tree(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Return the full downward hierarchy tree rooted at agent_id."""
        agent = await self._load_agent(agent_id, tenant_id)
        return await self._build_subtree(tenant_id, agent, visited=set())

    async def get_direct_supervisor_subordinate_ids(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        """Return IDs of all direct supervisor-type subordinates (for blackboard propagation)."""
        rels = await self.get_subordinates(
            tenant_id, agent_id, relation_type=AgentRelationTypeEnum.supervisor
        )
        return [r.subordinate_id for r in rels]

    async def _build_subtree(
        self,
        tenant_id: uuid.UUID,
        agent: Agent,
        visited: set[uuid.UUID],
    ) -> dict[str, Any]:
        if agent.id in visited:
            return {"id": str(agent.id), "name": agent.name, "subordinates": []}
        visited.add(agent.id)
        sub_rels = await self.get_subordinates(
            tenant_id, agent.id, relation_type=AgentRelationTypeEnum.supervisor
        )
        children = []
        for rel in sub_rels:
            child_agent = await self._load_agent(rel.subordinate_id, tenant_id)
            child_node = await self._build_subtree(tenant_id, child_agent, visited)
            children.append(child_node)
        return {"id": str(agent.id), "name": agent.name, "subordinates": children}

    async def _has_supervisor_path(
        self,
        tenant_id: uuid.UUID,
        from_id: uuid.UUID,
        to_id: uuid.UUID,
    ) -> bool:
        """Return True if from_id can reach to_id via supervisor-type relations."""
        visited: set[uuid.UUID] = set()
        queue = [from_id]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            for rel in await self.get_subordinates(
                tenant_id, current, relation_type=AgentRelationTypeEnum.supervisor
            ):
                if rel.subordinate_id == to_id:
                    return True
                queue.append(rel.subordinate_id)
        return False

    async def _load_agent(self, agent_id: uuid.UUID, tenant_id: uuid.UUID) -> Agent:
        agent = (await self._db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if agent is None:
            raise AgentNotFoundError(f"Agent {agent_id} not found")
        return agent

    async def _get_relation(
        self,
        tenant_id: uuid.UUID,
        supervisor_id: uuid.UUID,
        subordinate_id: uuid.UUID,
    ) -> AgentRelation | None:
        return (await self._db.execute(
            select(AgentRelation).where(
                AgentRelation.tenant_id == tenant_id,
                AgentRelation.supervisor_id == supervisor_id,
                AgentRelation.subordinate_id == subordinate_id,
            )
        )).scalar_one_or_none()
