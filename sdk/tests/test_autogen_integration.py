"""Tests for sdk/crewlayer/integrations/autogen.py.

All tests use mock clients — no real AutoGen or CrewLayer server required.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from crewlayer.integrations.autogen import (
    CrewLayerAgentMemory,
    CrewLayerConversableAgent,
    CrewLayerGroupChatManager,
    _extract_content,
    sync_agent_status,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_client(recall_results=None) -> MagicMock:
    client = MagicMock()
    client.memory.recall.return_value = SimpleNamespace(
        results=recall_results or []
    )
    return client


def _recall_item(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=str(uuid.uuid4()),
        content=content,
        similarity=0.88,
        importance=0.7,
        tags=[],
    )


def _fake_agent(name: str = "other") -> SimpleNamespace:
    return SimpleNamespace(name=name)


# ---------------------------------------------------------------------------
# _extract_content helper
# ---------------------------------------------------------------------------


def test_extract_content_plain_string() -> None:
    assert _extract_content("hello") == "hello"


def test_extract_content_dict_with_content_key() -> None:
    assert _extract_content({"content": "world", "role": "user"}) == "world"


def test_extract_content_dict_without_content_key() -> None:
    result = _extract_content({"tool_calls": [{"name": "search"}]})
    assert "search" in result


def test_extract_content_none() -> None:
    assert _extract_content(None) == ""


def test_extract_content_unknown_type() -> None:
    assert _extract_content(42) == "42"


# ---------------------------------------------------------------------------
# CrewLayerConversableAgent
# ---------------------------------------------------------------------------


class TestCrewLayerConversableAgent:
    def _agent(self, session_id: str = "s1") -> tuple:
        client = _make_client()
        agent = CrewLayerConversableAgent(
            name="researcher",
            client=client,
            agent_id="agent-uuid",
            session_id=session_id,
        )
        return agent, client

    # --- send ---------------------------------------------------------------

    def test_send_saves_to_memory_as_assistant(self) -> None:
        agent, client = self._agent()
        recipient = _fake_agent("writer")
        agent.send("Hello there", recipient)
        client.memory.append.assert_called_once()
        args = client.memory.append.call_args
        assert args[0][0] == "agent-uuid"
        assert args[0][1] == "assistant"
        assert args[0][2] == "Hello there"

    def test_send_logs_action_with_correct_tool_name(self) -> None:
        agent, client = self._agent()
        agent.send("test msg", _fake_agent())
        client.actions.log.assert_called_once()
        kw = client.actions.log.call_args[1]
        assert kw["tool_name"] == "autogen.send"
        assert kw["status"] == "success"

    def test_send_includes_recipient_name_in_action(self) -> None:
        agent, client = self._agent()
        agent.send("hi", _fake_agent("writer"))
        kw = client.actions.log.call_args[1]
        assert kw["input_params"]["to"] == "writer"

    def test_send_duration_ms_is_non_negative_int(self) -> None:
        agent, client = self._agent()
        agent.send("msg", _fake_agent())
        kw = client.actions.log.call_args[1]
        assert isinstance(kw["duration_ms"], int)
        assert kw["duration_ms"] >= 0

    def test_send_session_id_forwarded(self) -> None:
        agent, client = self._agent(session_id="sess-99")
        agent.send("msg", _fake_agent())
        kw = client.actions.log.call_args[1]
        assert kw["session_id"] == "sess-99"

    def test_send_handles_dict_message(self) -> None:
        agent, client = self._agent()
        agent.send({"content": "dict content", "role": "assistant"}, _fake_agent())
        mem_args = client.memory.append.call_args
        assert mem_args[0][2] == "dict content"

    def test_send_failure_does_not_propagate(self) -> None:
        agent, client = self._agent()
        client.memory.append.side_effect = RuntimeError("network down")
        agent.send("msg", _fake_agent())  # must not raise
        client.actions.log.assert_called_once()

    def test_send_action_log_failure_does_not_propagate(self) -> None:
        agent, client = self._agent()
        client.actions.log.side_effect = RuntimeError("server error")
        agent.send("msg", _fake_agent())  # must not raise

    # --- receive ------------------------------------------------------------

    def test_receive_saves_to_memory_as_user(self) -> None:
        agent, client = self._agent()
        sender = _fake_agent("manager")
        agent.receive("Request received", sender)
        client.memory.append.assert_called_once()
        args = client.memory.append.call_args
        assert args[0][0] == "agent-uuid"
        assert args[0][1] == "user"
        assert args[0][2] == "Request received"

    def test_receive_logs_action_with_correct_tool_name(self) -> None:
        agent, client = self._agent()
        agent.receive("msg", _fake_agent())
        kw = client.actions.log.call_args[1]
        assert kw["tool_name"] == "autogen.receive"
        assert kw["status"] == "success"

    def test_receive_includes_sender_name_in_action(self) -> None:
        agent, client = self._agent()
        agent.receive("hello", _fake_agent("researcher"))
        kw = client.actions.log.call_args[1]
        assert kw["input_params"]["from"] == "researcher"

    def test_receive_memory_saved_before_action_log(self) -> None:
        """For receive: memory.append must appear before actions.log in mock_calls.

        Implementation: _cl_save() before super(), _cl_log() after super().
        This ensures the message is persisted even if processing later raises.
        """
        client = _make_client()
        agent = CrewLayerConversableAgent(name="t", client=client, agent_id="a1")
        agent.receive("msg", _fake_agent())
        # Both memory.append and actions.log must be called, in that order
        call_names = [
            c[0] for c in client.mock_calls
            if c[0] in ("memory.append", "actions.log")
        ]
        assert call_names == ["memory.append", "actions.log"]

    def test_receive_session_id_forwarded(self) -> None:
        agent, client = self._agent(session_id="recv-sess")
        agent.receive("msg", _fake_agent())
        kw = client.memory.append.call_args[1]
        assert kw["session_id"] == "recv-sess"

    def test_receive_failure_does_not_propagate(self) -> None:
        agent, client = self._agent()
        client.memory.append.side_effect = RuntimeError("down")
        agent.receive("msg", _fake_agent())  # must not raise

    def test_receive_handles_dict_message(self) -> None:
        agent, client = self._agent()
        agent.receive({"content": "incoming dict"}, _fake_agent())
        assert client.memory.append.call_args[0][2] == "incoming dict"

    def test_memory_metadata_contains_direction(self) -> None:
        agent, client = self._agent()
        agent.send("outgoing", _fake_agent("b"))
        kw = client.memory.append.call_args[1]
        assert kw["metadata"]["direction"] == "send"

    def test_receive_metadata_contains_direction(self) -> None:
        agent, client = self._agent()
        agent.receive("incoming", _fake_agent("a"))
        kw = client.memory.append.call_args[1]
        assert kw["metadata"]["direction"] == "receive"


# ---------------------------------------------------------------------------
# CrewLayerGroupChatManager
# ---------------------------------------------------------------------------


class TestCrewLayerGroupChatManager:
    def _manager(self, group_id: str = "gc-test") -> tuple:
        client = _make_client()
        manager = CrewLayerGroupChatManager(
            client=client,
            group_id=group_id,
            name="manager",
        )
        return manager, client

    def test_receive_writes_latest_turn_to_blackboard(self) -> None:
        manager, client = self._manager("room-1")
        sender = _fake_agent("alice")
        manager.receive("Hello group", sender)
        writes = [c for c in client.context.write.call_args_list
                  if c[0][1] == "latest_turn"]
        assert len(writes) == 1
        payload = writes[0][0][2]
        assert payload["agent"] == "alice"
        assert "Hello group" in payload["content"]

    def test_receive_writes_agent_namespace_key(self) -> None:
        manager, client = self._manager("room-1")
        sender = _fake_agent("bob")
        manager.receive("My message", sender)
        writes = [c for c in client.context.write.call_args_list
                  if c[0][1] == "agent:bob"]
        assert len(writes) == 1
        assert "My message" in writes[0][0][2]["last_message"]

    def test_receive_uses_correct_group_id_namespace(self) -> None:
        manager, client = self._manager("project-alpha")
        manager.receive("msg", _fake_agent("x"))
        namespaces = [c[0][0] for c in client.context.write.call_args_list]
        assert all(ns == "project-alpha" for ns in namespaces)

    def test_receive_increments_turn_counter(self) -> None:
        manager, client = self._manager()
        manager.receive("turn 1", _fake_agent("a"))
        manager.receive("turn 2", _fake_agent("b"))
        assert manager._cl_turn == 2

    def test_receive_turn_counter_in_blackboard_payload(self) -> None:
        manager, client = self._manager()
        manager.receive("first", _fake_agent("a"))
        manager.receive("second", _fake_agent("b"))
        latest_turns = [
            c[0][2] for c in client.context.write.call_args_list
            if c[0][1] == "latest_turn"
        ]
        assert latest_turns[0]["turn"] == 1
        assert latest_turns[1]["turn"] == 2

    def test_receive_written_by_is_sender_name(self) -> None:
        manager, client = self._manager()
        manager.receive("msg", _fake_agent("charlie"))
        first_call = client.context.write.call_args_list[0]
        assert first_call[1].get("written_by") == "charlie"

    def test_blackboard_failure_does_not_block_receive(self) -> None:
        manager, client = self._manager()
        client.context.write.side_effect = RuntimeError("blackboard down")
        manager.receive("msg", _fake_agent())  # must not raise

    def test_default_group_id_uses_manager_name(self) -> None:
        client = _make_client()
        manager = CrewLayerGroupChatManager(client=client, name="my_manager")
        assert manager._cl_group_id == "groupchat:my_manager"

    def test_get_shared_context_calls_list_namespace(self) -> None:
        manager, client = self._manager("ctx-ns")
        manager.get_shared_context()
        client.context.list_namespace.assert_called_once_with("ctx-ns")

    def test_two_agents_write_separate_keys(self) -> None:
        manager, client = self._manager()
        manager.receive("msg A", _fake_agent("agent_a"))
        manager.receive("msg B", _fake_agent("agent_b"))
        agent_keys = {
            c[0][1]
            for c in client.context.write.call_args_list
            if c[0][1].startswith("agent:")
        }
        assert "agent:agent_a" in agent_keys
        assert "agent:agent_b" in agent_keys

    def test_receive_writes_exactly_two_entries_per_turn(self) -> None:
        manager, client = self._manager()
        manager.receive("msg", _fake_agent("x"))
        assert client.context.write.call_count == 2


# ---------------------------------------------------------------------------
# CrewLayerAgentMemory
# ---------------------------------------------------------------------------


class TestCrewLayerAgentMemory:
    def _fake_agent_with_system_msg(self, msg: str = "") -> MagicMock:
        agent = MagicMock()
        agent.system_message = msg
        return agent

    def test_apply_prepends_memories_to_system_message(self) -> None:
        items = [_recall_item("User is a Python developer"), _recall_item("Prefers dark mode")]
        client = _make_client(recall_results=items)
        mem = CrewLayerAgentMemory(client=client, agent_id="a1")
        agent = self._fake_agent_with_system_msg("You are an assistant.")
        mem.apply(agent)
        new_msg = agent.update_system_message.call_args[0][0]
        assert "Python developer" in new_msg
        assert "Prefers dark mode" in new_msg
        assert "You are an assistant." in new_msg

    def test_apply_memories_come_before_system_message(self) -> None:
        items = [_recall_item("memory content")]
        client = _make_client(recall_results=items)
        mem = CrewLayerAgentMemory(client=client, agent_id="a1")
        agent = self._fake_agent_with_system_msg("original prompt")
        mem.apply(agent)
        new_msg = agent.update_system_message.call_args[0][0]
        assert new_msg.index("memory content") < new_msg.index("original prompt")

    def test_apply_no_memories_leaves_agent_unchanged(self) -> None:
        client = _make_client(recall_results=[])
        mem = CrewLayerAgentMemory(client=client, agent_id="a1")
        agent = self._fake_agent_with_system_msg("original")
        mem.apply(agent)
        agent.update_system_message.assert_not_called()

    def test_apply_empty_system_message(self) -> None:
        items = [_recall_item("only memory")]
        client = _make_client(recall_results=items)
        mem = CrewLayerAgentMemory(client=client, agent_id="a1")
        agent = self._fake_agent_with_system_msg("")
        mem.apply(agent)
        new_msg = agent.update_system_message.call_args[0][0]
        assert "only memory" in new_msg

    def test_apply_uses_update_system_message_when_available(self) -> None:
        items = [_recall_item("fact")]
        client = _make_client(recall_results=items)
        mem = CrewLayerAgentMemory(client=client, agent_id="a1")
        agent = self._fake_agent_with_system_msg("base")
        mem.apply(agent)
        agent.update_system_message.assert_called_once()

    def test_apply_falls_back_to_direct_assignment(self) -> None:
        items = [_recall_item("remembered fact")]
        client = _make_client(recall_results=items)
        mem = CrewLayerAgentMemory(client=client, agent_id="a1")
        # Agent without update_system_message method
        agent = SimpleNamespace(system_message="base msg")
        mem.apply(agent)
        assert "remembered fact" in agent.system_message

    def test_apply_uses_custom_query(self) -> None:
        client = _make_client()
        mem = CrewLayerAgentMemory(client=client, agent_id="a1", query="sales context")
        agent = self._fake_agent_with_system_msg("")
        mem.apply(agent)
        args = client.memory.recall.call_args
        assert args[0][1] == "sales context"

    def test_apply_uses_limit(self) -> None:
        client = _make_client()
        mem = CrewLayerAgentMemory(client=client, agent_id="a1", limit=3)
        agent = self._fake_agent_with_system_msg("")
        mem.apply(agent)
        kw = client.memory.recall.call_args[1]
        assert kw["limit"] == 3

    def test_apply_formats_each_memory_as_bullet(self) -> None:
        items = [_recall_item("fact A"), _recall_item("fact B")]
        client = _make_client(recall_results=items)
        mem = CrewLayerAgentMemory(client=client, agent_id="a1")
        agent = self._fake_agent_with_system_msg("")
        mem.apply(agent)
        new_msg = agent.update_system_message.call_args[0][0]
        assert "- fact A" in new_msg
        assert "- fact B" in new_msg


# ---------------------------------------------------------------------------
# sync_agent_status
# ---------------------------------------------------------------------------


class TestSyncAgentStatus:
    def _client_with_http(self) -> MagicMock:
        client = MagicMock()
        return client

    def test_thinking_maps_to_working(self) -> None:
        client = self._client_with_http()
        sync_agent_status(client, "a1", "thinking")
        kw = client._http.request.call_args[1]
        assert kw["json"]["status"] == "working"

    def test_replying_maps_to_working(self) -> None:
        client = self._client_with_http()
        sync_agent_status(client, "a1", "replying")
        assert client._http.request.call_args[1]["json"]["status"] == "working"

    def test_generating_maps_to_working(self) -> None:
        client = self._client_with_http()
        sync_agent_status(client, "a1", "generating")
        assert client._http.request.call_args[1]["json"]["status"] == "working"

    def test_idle_maps_to_idle(self) -> None:
        client = self._client_with_http()
        sync_agent_status(client, "a1", "idle")
        assert client._http.request.call_args[1]["json"]["status"] == "idle"

    def test_waiting_maps_to_idle(self) -> None:
        client = self._client_with_http()
        sync_agent_status(client, "a1", "waiting")
        assert client._http.request.call_args[1]["json"]["status"] == "idle"

    def test_error_maps_to_error(self) -> None:
        client = self._client_with_http()
        sync_agent_status(client, "a1", "error")
        assert client._http.request.call_args[1]["json"]["status"] == "error"

    def test_unknown_status_defaults_to_idle(self) -> None:
        client = self._client_with_http()
        sync_agent_status(client, "a1", "some_unknown_state")
        assert client._http.request.call_args[1]["json"]["status"] == "idle"

    def test_status_is_case_insensitive(self) -> None:
        client = self._client_with_http()
        sync_agent_status(client, "a1", "THINKING")
        assert client._http.request.call_args[1]["json"]["status"] == "working"

    def test_sends_patch_to_correct_endpoint(self) -> None:
        client = self._client_with_http()
        sync_agent_status(client, "my-agent-id", "idle")
        args = client._http.request.call_args[0]
        assert args[0] == "PATCH"
        assert "my-agent-id" in args[1]

    def test_session_id_included_in_payload(self) -> None:
        client = self._client_with_http()
        sync_agent_status(client, "a1", "thinking", session_id="s42")
        kw = client._http.request.call_args[1]
        assert kw["json"]["session_id"] == "s42"

    def test_failure_does_not_propagate(self) -> None:
        client = self._client_with_http()
        client._http.request.side_effect = RuntimeError("network down")
        sync_agent_status(client, "a1", "thinking")  # must not raise
