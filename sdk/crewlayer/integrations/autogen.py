"""Microsoft AutoGen integration for the CrewLayer SDK.

Provides four adapters purpose-built for multi-agent workflows:

- ``CrewLayerConversableAgent``  — ConversableAgent that persists every
                                    message to CrewLayer memory and logs
                                    each send/receive as an action
- ``CrewLayerGroupChatManager`` — GroupChatManager that keeps the shared
                                    CrewLayer blackboard in sync after every
                                    group chat turn (the killer feature for
                                    multi-agent workflows)
- ``CrewLayerAgentMemory``       — helper that loads an agent's long-term
                                    memories as initial system context
- ``sync_agent_status``          — maps AutoGen thinking/idle states to
                                    CrewLayer working/idle

Install::

    pip install crewlayer[autogen]

Usage::

    from crewlayer import CrewLayerClient
    from crewlayer.integrations.autogen import (
        CrewLayerConversableAgent,
        CrewLayerGroupChatManager,
        CrewLayerAgentMemory,
        sync_agent_status,
    )
    import autogen

    client = CrewLayerClient(api_key="crwl_...")

    agent_a = CrewLayerConversableAgent(
        name="researcher",
        client=client,
        agent_id="<uuid-a>",
        system_message="You are a research assistant.",
        llm_config={"model": "gpt-4"},
    )
    agent_b = CrewLayerConversableAgent(
        name="writer",
        client=client,
        agent_id="<uuid-b>",
        system_message="You are a technical writer.",
        llm_config={"model": "gpt-4"},
    )

    groupchat = autogen.GroupChat(agents=[agent_a, agent_b], messages=[], max_round=10)
    manager = CrewLayerGroupChatManager(
        client=client,
        group_id="project-alpha",
        groupchat=groupchat,
    )

    # Load long-term memories as initial context
    CrewLayerAgentMemory(client=client, agent_id="<uuid-a>").apply(agent_a)

    # Every turn → blackboard updated automatically
    agent_a.initiate_chat(manager, message="Let's start researching CrewLayer.")
"""
from __future__ import annotations

import time
from typing import Any

# ---------------------------------------------------------------------------
# Optional AutoGen imports — graceful fallback when not installed
# ---------------------------------------------------------------------------

try:
    from autogen import ConversableAgent as _AGConversableAgent  # type: ignore[import]
    from autogen import GroupChatManager as _AGGroupChatManager  # type: ignore[import]
    _AUTOGEN = True
except ImportError:
    _AUTOGEN = False

    class _AutoGenStub:  # type: ignore[no-redef]
        """Minimal stub for testing without AutoGen installed."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.name: str = str(kwargs.get("name", ""))
            self.system_message: str = str(kwargs.get("system_message", ""))

        def send(self, message: Any, recipient: Any, **kwargs: Any) -> None:
            pass

        def receive(self, message: Any, sender: Any, **kwargs: Any) -> None:
            pass

        def update_system_message(self, system_message: str) -> None:
            self.system_message = system_message

    _AGConversableAgent = _AutoGenStub  # type: ignore[assignment, misc]
    _AGGroupChatManager = _AutoGenStub  # type: ignore[assignment, misc]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# AutoGen agent-status → CrewLayer status
_STATUS_MAP: dict[str, str] = {
    "thinking": "working",
    "replying": "working",
    "generating": "working",
    "processing": "working",
    "waiting": "idle",
    "idle": "idle",
    "error": "error",
}


def _extract_content(message: Any) -> str:
    """Return plain-text content from an AutoGen message (str or dict)."""
    if message is None:
        return ""
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        content = message.get("content")
        if content is not None:
            return str(content)
        if "tool_calls" in message:
            return str(message["tool_calls"])
        return str(message)
    return str(message)


def _agent_name(agent: Any) -> str:
    return getattr(agent, "name", None) or str(agent)


# ---------------------------------------------------------------------------
# CrewLayerConversableAgent
# ---------------------------------------------------------------------------


class CrewLayerConversableAgent(_AGConversableAgent):  # type: ignore[misc]
    """AutoGen ``ConversableAgent`` with automatic CrewLayer persistence.

    Every message sent or received is:
    - appended to CrewLayer short-term memory (builds conversation history)
    - logged as an immutable action entry (full audit trail with duration)

    CrewLayer-specific parameters are keyword-only and separated from the
    AutoGen parameters, so all existing AutoGen kwargs pass through unchanged.

    Args:
        name:       Agent name (forwarded to AutoGen).
        client:     A ``CrewLayerClient`` (sync) instance.
        agent_id:   Target agent UUID in CrewLayer.
        session_id: Session key for short-term memory (default ``"default"``).
        **kwargs:   All other kwargs forwarded to ``ConversableAgent.__init__``.

    Example::

        agent = CrewLayerConversableAgent(
            name="assistant",
            client=client,
            agent_id="agent-uuid",
            system_message="You are helpful.",
            llm_config={"model": "gpt-4"},
        )
    """

    def __init__(
        self,
        name: str,
        *,
        client: Any,
        agent_id: str,
        session_id: str = "default",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, **kwargs)
        # __dict__ assignment bypasses Pydantic __setattr__ if AutoGen ever
        # switches to Pydantic models.
        self.__dict__.update({
            "_cl_client": client,
            "_cl_agent_id": agent_id,
            "_cl_session": session_id,
        })

    # ------------------------------------------------------------------
    # AutoGen ConversableAgent overrides
    # ------------------------------------------------------------------

    def send(
        self,
        message: Any,
        recipient: Any,
        request_reply: bool | None = None,
        silent: bool | None = False,
    ) -> None:
        """Send a message; log the action and persist to memory afterwards."""
        start = time.monotonic()
        result = super().send(
            message, recipient,
            request_reply=request_reply,
            silent=silent,
        )
        duration_ms = max(0, int((time.monotonic() - start) * 1000))
        content = _extract_content(message)
        recipient_name = _agent_name(recipient)
        self._cl_save(
            role="assistant",
            content=content,
            metadata={"direction": "send", "to": recipient_name},
        )
        self._cl_log(
            tool_name="autogen.send",
            input_params={"message": content[:500], "to": recipient_name},
            output_result={},
            duration_ms=duration_ms,
        )
        return result

    def receive(
        self,
        message: Any,
        sender: Any,
        request_reply: bool | None = None,
        silent: bool | None = False,
    ) -> None:
        """Receive a message; persist to memory first, then log the action."""
        content = _extract_content(message)
        sender_name = _agent_name(sender)

        # Save the incoming message before processing so it's preserved even
        # if processing later raises.
        self._cl_save(
            role="user",
            content=content,
            metadata={"direction": "receive", "from": sender_name},
        )

        start = time.monotonic()
        result = super().receive(
            message, sender,
            request_reply=request_reply,
            silent=silent,
        )
        duration_ms = max(0, int((time.monotonic() - start) * 1000))

        self._cl_log(
            tool_name="autogen.receive",
            input_params={"message": content[:500], "from": sender_name},
            output_result={},
            duration_ms=duration_ms,
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cl_save(self, role: str, content: str, metadata: dict | None = None) -> None:
        """Append a message to CrewLayer short-term memory — never raises."""
        try:
            self._cl_client.memory.append(
                self._cl_agent_id,
                role,
                content,
                session_id=self._cl_session,
                metadata=metadata or {},
            )
        except Exception:
            pass

    def _cl_log(
        self,
        tool_name: str,
        input_params: dict,
        output_result: dict,
        duration_ms: int | None = None,
    ) -> None:
        """Log an action to CrewLayer — never raises."""
        try:
            self._cl_client.actions.log(
                self._cl_agent_id,
                tool_name=tool_name,
                input_params=input_params,
                output_result=output_result,
                status="success",
                session_id=self._cl_session,
                duration_ms=duration_ms,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CrewLayerGroupChatManager
# ---------------------------------------------------------------------------


class CrewLayerGroupChatManager(_AGGroupChatManager):  # type: ignore[misc]
    """AutoGen ``GroupChatManager`` that syncs every turn to the CrewLayer blackboard.

    After each message in the group chat, two blackboard entries are written:

    * ``latest_turn`` — the most recent speaker, content, and turn counter
    * ``agent:{name}`` — each speaker's most recent message

    This gives every agent (and external observers) a shared, persistent view
    of the conversation state at ``context.read(group_id, "latest_turn")``.

    Args:
        client:    A ``CrewLayerClient`` (sync) instance.
        group_id:  Blackboard namespace (default: ``"groupchat:{manager_name}"``).
        groupchat: The ``autogen.GroupChat`` instance (forwarded to AutoGen).
        name:      Manager agent name (default ``"group_chat_manager"``).
        **kwargs:  All other kwargs forwarded to ``GroupChatManager.__init__``.

    Example::

        groupchat = autogen.GroupChat(agents=[a, b], messages=[], max_round=10)
        manager = CrewLayerGroupChatManager(
            client=client,
            group_id="project-alpha",
            groupchat=groupchat,
        )
        # After each turn: client.context.read("project-alpha", "latest_turn")
    """

    def __init__(
        self,
        *,
        client: Any,
        group_id: str | None = None,
        groupchat: Any = None,
        name: str = "group_chat_manager",
        **kwargs: Any,
    ) -> None:
        if groupchat is not None:
            super().__init__(groupchat=groupchat, name=name, **kwargs)
        else:
            super().__init__(name=name, **kwargs)

        effective_group_id = group_id or f"groupchat:{name}"
        self.__dict__.update({
            "_cl_client": client,
            "_cl_group_id": effective_group_id,
            "_cl_turn": 0,
        })

    # ------------------------------------------------------------------
    # AutoGen GroupChatManager override
    # ------------------------------------------------------------------

    def receive(
        self,
        message: Any,
        sender: Any,
        request_reply: bool | None = None,
        silent: bool | None = False,
    ) -> None:
        """Process a group chat message and sync state to the blackboard."""
        result = super().receive(
            message, sender,
            request_reply=request_reply,
            silent=silent,
        )
        try:
            self._cl_write_blackboard(message, sender)
        except Exception:
            pass  # Never block group chat coordination
        return result

    # ------------------------------------------------------------------
    # Blackboard helpers
    # ------------------------------------------------------------------

    def _cl_write_blackboard(self, message: Any, sender: Any) -> None:
        """Write sender's message to the shared blackboard namespace."""
        self._cl_turn += 1
        content = _extract_content(message)
        sender_name = _agent_name(sender)

        self._cl_client.context.write(
            self._cl_group_id,
            "latest_turn",
            {
                "agent": sender_name,
                "content": content[:1000],
                "turn": self._cl_turn,
            },
            written_by=sender_name,
        )
        self._cl_client.context.write(
            self._cl_group_id,
            f"agent:{sender_name}",
            {
                "last_message": content[:1000],
                "turn": self._cl_turn,
            },
            written_by=sender_name,
        )

    def get_shared_context(self) -> Any:
        """Return all blackboard entries for this group's namespace.

        Returns a ``ContextNamespace`` with a list of ``ContextEntry`` objects,
        one per agent and the ``latest_turn`` entry.

        Example::

            ctx = manager.get_shared_context()
            for entry in ctx.entries:
                print(f"{entry.key}: {entry.value}")
        """
        return self._cl_client.context.list_namespace(self._cl_group_id)


# ---------------------------------------------------------------------------
# CrewLayerAgentMemory
# ---------------------------------------------------------------------------


class CrewLayerAgentMemory:
    """Loads an agent's long-term memories as initial system context.

    Call ``apply(agent)`` before starting a conversation to pre-load relevant
    memories into the agent's system message.  Useful for giving agents
    continuity across sessions without manually managing context.

    Args:
        client:    A ``CrewLayerClient`` (sync) instance.
        agent_id:  Target agent UUID.
        query:     Semantic query used to select relevant memories
                   (default: ``"agent background context and history"``).
        limit:     Maximum number of memories to load (default ``5``).

    Example::

        mem = CrewLayerAgentMemory(client=client, agent_id="agent-uuid")
        mem.apply(agent)            # enriches agent.system_message
        agent.initiate_chat(other, message="Hello")
    """

    def __init__(
        self,
        *,
        client: Any,
        agent_id: str,
        query: str = "agent background context and history",
        limit: int = 5,
    ) -> None:
        self._client = client
        self._agent_id = agent_id
        self._query = query
        self._limit = limit

    def apply(self, agent: Any) -> None:
        """Prepend relevant long-term memories to *agent*'s system message.

        If no memories are found the agent is left unchanged.
        Respects AutoGen's ``update_system_message()`` API; falls back to
        direct attribute assignment for custom or stub agents.
        """
        results = self._client.memory.recall(
            self._agent_id, self._query, limit=self._limit
        )
        if not results.results:
            return

        memory_lines = "\n".join(f"- {item.content}" for item in results.results)
        memory_block = (
            "Relevant memories from previous sessions:\n" + memory_lines
        )

        current = getattr(agent, "system_message", "") or ""
        new_message = f"{memory_block}\n\n{current}" if current else memory_block

        if callable(getattr(agent, "update_system_message", None)):
            agent.update_system_message(new_message)
        else:
            try:
                agent.system_message = new_message
            except (AttributeError, TypeError):
                pass


# ---------------------------------------------------------------------------
# sync_agent_status
# ---------------------------------------------------------------------------


def sync_agent_status(
    client: Any,
    agent_id: str,
    autogen_status: str,
    *,
    session_id: str | None = None,
) -> None:
    """Synchronise an AutoGen agent state with CrewLayer's agent status.

    AutoGen status strings are mapped to CrewLayer's status enum:

    +--------------+------------------+
    | AutoGen      | CrewLayer        |
    +==============+==================+
    | thinking     | working          |
    | replying     | working          |
    | generating   | working          |
    | processing   | working          |
    | waiting      | idle             |
    | idle         | idle             |
    | error        | error            |
    +--------------+------------------+

    Unknown strings default to ``idle``.

    The call is best-effort — it silently swallows all exceptions so it never
    blocks the agent's execution.

    Args:
        client:         A ``CrewLayerClient`` (sync) instance.
        agent_id:       Target agent UUID.
        autogen_status: AutoGen status string (case-insensitive).
        session_id:     Optional current session to associate with the status.

    Example::

        sync_agent_status(client, agent_id, "thinking")
        response = agent.generate_reply(messages)
        sync_agent_status(client, agent_id, "idle")
    """
    crewlayer_status = _STATUS_MAP.get(autogen_status.lower(), "idle")
    try:
        client._http.request(
            "PATCH",
            f"/v1/agents/{agent_id}/status",
            json={"status": crewlayer_status, "session_id": session_id},
        )
    except Exception:
        pass
