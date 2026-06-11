"""CLI tests — uses CliRunner + httpx mocks (no real server needed)."""
import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from crewlayer.cli.main import app

runner = CliRunner()

_TENANT_ID = str(uuid.uuid4())
_AGENT_ID = str(uuid.uuid4())
_KEY_ID = str(uuid.uuid4())

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_resp(data, status_code: int = 200) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = data
    m.text = json.dumps(data)
    return m


def _patch_client(mocker, data, status_code: int = 200):
    mock_client = MagicMock()
    mock_client.request.return_value = _mock_resp(data, status_code)
    mocker.patch("crewlayer.cli.client.get_client", return_value=mock_client)
    return mock_client


def _patch_config(mocker):
    mocker.patch(
        "crewlayer.cli.config.load",
        return_value={"url": "http://localhost:8000", "api_key": "crwl_test_key"},
    )


# ---------------------------------------------------------------------------
# tenants create
# ---------------------------------------------------------------------------

def test_tenants_create(mocker):
    _patch_config(mocker)
    _patch_client(mocker, {
        "id": _TENANT_ID,
        "name": "mi proyecto",
        "plan": "free",
        "created_at": "2024-01-01T00:00:00",
        "initial_api_key": "crwl_abc123",
    }, 201)

    result = runner.invoke(app, ["tenants", "create", "--name", "mi proyecto"])

    assert result.exit_code == 0, result.output
    assert "mi proyecto" in result.output
    assert "crwl_abc123" in result.output


def test_tenants_create_json(mocker):
    _patch_config(mocker)
    data = {
        "id": _TENANT_ID, "name": "x", "plan": "free",
        "created_at": "2024-01-01T00:00:00", "initial_api_key": "crwl_key",
    }
    _patch_client(mocker, data, 201)

    result = runner.invoke(app, ["tenants", "create", "--name", "x", "--json"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["name"] == "x"


# ---------------------------------------------------------------------------
# keys create / list
# ---------------------------------------------------------------------------

def test_keys_create(mocker):
    _patch_config(mocker)
    _patch_client(mocker, {
        "id": _KEY_ID, "name": "produccion",
        "scopes": ["memory:read", "memory:write"],
        "agent_ids": [], "last_used_at": None, "expires_at": None,
        "key": "crwl_newkey_abc",
    }, 201)

    result = runner.invoke(app, [
        "keys", "create",
        "--name", "produccion",
        "--scopes", "memory:read,memory:write",
    ])

    assert result.exit_code == 0, result.output
    assert "crwl_newkey_abc" in result.output
    assert "produccion" in result.output


def test_keys_list(mocker):
    _patch_config(mocker)
    _patch_client(mocker, [
        {
            "id": _KEY_ID, "name": "default",
            "scopes": [], "agent_ids": [],
            "last_used_at": "2024-01-10T12:00:00", "expires_at": None,
        }
    ])

    result = runner.invoke(app, ["keys", "list"])

    assert result.exit_code == 0, result.output
    assert "default" in result.output


def test_keys_list_json(mocker):
    _patch_config(mocker)
    data = [{"id": _KEY_ID, "name": "k1", "scopes": [], "agent_ids": [],
              "last_used_at": None, "expires_at": None}]
    _patch_client(mocker, data)

    result = runner.invoke(app, ["keys", "list", "--json"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed[0]["name"] == "k1"


def test_keys_list_empty(mocker):
    _patch_config(mocker)
    _patch_client(mocker, [])
    result = runner.invoke(app, ["keys", "list"])
    assert result.exit_code == 0
    assert "No API keys" in result.output


# ---------------------------------------------------------------------------
# agents list / create / status
# ---------------------------------------------------------------------------

def test_agents_list(mocker):
    _patch_config(mocker)
    _patch_client(mocker, [
        {
            "id": _AGENT_ID, "tenant_id": _TENANT_ID,
            "name": "asistente", "status": "idle",
            "tags": ["ventas"], "config": {},
            "current_session_id": None,
            "status_updated_at": "2024-01-01T00:00:00",
            "description": None,
        }
    ])

    result = runner.invoke(app, ["agents", "list"])

    assert result.exit_code == 0, result.output
    assert "asistente" in result.output
    assert "idle" in result.output
    assert "ventas" in result.output


def test_agents_list_with_tags_filter(mocker):
    _patch_config(mocker)
    mock_client = _patch_client(mocker, [])

    runner.invoke(app, ["agents", "list", "--tags", "produccion"])

    call_kwargs = mock_client.request.call_args
    assert "produccion" in str(call_kwargs)


def test_agents_list_json(mocker):
    _patch_config(mocker)
    data = [{
        "id": _AGENT_ID, "tenant_id": _TENANT_ID,
        "name": "bot", "status": "working",
        "tags": [], "config": {},
        "current_session_id": None,
        "status_updated_at": "2024-01-01T00:00:00",
        "description": None,
    }]
    _patch_client(mocker, data)

    result = runner.invoke(app, ["agents", "list", "--json"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed[0]["name"] == "bot"


def test_agents_list_empty(mocker):
    _patch_config(mocker)
    _patch_client(mocker, [])
    result = runner.invoke(app, ["agents", "list"])
    assert result.exit_code == 0
    assert "No agents" in result.output


def test_agents_create(mocker):
    _patch_config(mocker)
    _patch_client(mocker, {
        "id": _AGENT_ID, "tenant_id": _TENANT_ID,
        "name": "asistente", "status": "idle",
        "tags": ["ventas"], "config": {},
        "current_session_id": None,
        "status_updated_at": "2024-01-01T00:00:00",
        "description": None,
    }, 201)

    result = runner.invoke(app, [
        "agents", "create",
        "--name", "asistente",
        "--tags", "ventas",
    ])

    assert result.exit_code == 0, result.output
    assert "asistente" in result.output
    assert _AGENT_ID in result.output


def test_agents_create_json(mocker):
    _patch_config(mocker)
    data = {
        "id": _AGENT_ID, "tenant_id": _TENANT_ID,
        "name": "bot", "status": "idle",
        "tags": [], "config": {},
        "current_session_id": None,
        "status_updated_at": "2024-01-01T00:00:00",
        "description": None,
    }
    _patch_client(mocker, data, 201)

    result = runner.invoke(app, ["agents", "create", "--name", "bot", "--json"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["name"] == "bot"


def test_agents_status(mocker):
    _patch_config(mocker)
    _patch_client(mocker, {
        "agent_id": _AGENT_ID,
        "status": "working",
        "current_session_id": str(uuid.uuid4()),
        "updated_at": "2024-01-15T10:30:00",
    })

    result = runner.invoke(app, ["agents", "status", _AGENT_ID])

    assert result.exit_code == 0, result.output
    assert "working" in result.output


def test_agents_status_json(mocker):
    _patch_config(mocker)
    data = {
        "agent_id": _AGENT_ID, "status": "idle",
        "current_session_id": None, "updated_at": "2024-01-01T00:00:00",
    }
    _patch_client(mocker, data)

    result = runner.invoke(app, ["agents", "status", _AGENT_ID, "--json"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["status"] == "idle"


# ---------------------------------------------------------------------------
# memory recall / list
# ---------------------------------------------------------------------------

def test_memory_recall(mocker):
    _patch_config(mocker)
    _patch_client(mocker, {
        "query": "preferencias del usuario",
        "results": [
            {
                "id": str(uuid.uuid4()),
                "content": "El usuario prefiere respuestas cortas.",
                "importance": 0.85,
                "base_importance": 0.8,
                "similarity": 0.92,
                "tags": [],
                "merged_from": [],
                "created_at": "2024-01-01T00:00:00",
                "status": "active",
            }
        ],
    })

    result = runner.invoke(app, ["memory", "recall", _AGENT_ID, "preferencias del usuario"])

    assert result.exit_code == 0, result.output
    assert "preferencias del usuario" in result.output
    assert "respuestas cortas" in result.output


def test_memory_recall_no_results(mocker):
    _patch_config(mocker)
    _patch_client(mocker, {"query": "nada", "results": []})
    result = runner.invoke(app, ["memory", "recall", _AGENT_ID, "nada"])
    assert result.exit_code == 0
    assert "No memories" in result.output


def test_memory_recall_json(mocker):
    _patch_config(mocker)
    data = {"query": "q", "results": []}
    _patch_client(mocker, data)
    result = runner.invoke(app, ["memory", "recall", _AGENT_ID, "q", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["query"] == "q"


def test_memory_list(mocker):
    _patch_config(mocker)
    _patch_client(mocker, {
        "items": [
            {
                "id": str(uuid.uuid4()),
                "content": "Usuario trabaja en fintech.",
                "importance": 0.7,
                "base_importance": 0.7,
                "status": "active",
                "tags": [],
                "merged_from": [],
                "created_at": "2024-01-01T00:00:00",
            }
        ],
        "total": 1, "page": 1, "page_size": 20,
    })

    result = runner.invoke(app, ["memory", "list", _AGENT_ID, "--limit", "20"])

    assert result.exit_code == 0, result.output
    assert "fintech" in result.output


def test_memory_list_json(mocker):
    _patch_config(mocker)
    data = {"items": [], "total": 0, "page": 1, "page_size": 20}
    _patch_client(mocker, data)
    result = runner.invoke(app, ["memory", "list", _AGENT_ID, "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["total"] == 0


# ---------------------------------------------------------------------------
# actions list / stats
# ---------------------------------------------------------------------------

def test_actions_list(mocker):
    _patch_config(mocker)
    _patch_client(mocker, {
        "items": [
            {
                "id": str(uuid.uuid4()),
                "agent_id": _AGENT_ID,
                "tenant_id": _TENANT_ID,
                "tool_name": "web_search",
                "status": "success",
                "duration_ms": 320,
                "timestamp": "2024-01-15T10:30:00",
                "input_params": {}, "output_result": {},
                "error_msg": None, "session_id": None, "metadata": {},
            }
        ],
        "count": 1, "next_cursor": None,
    })

    result = runner.invoke(app, ["actions", "list", _AGENT_ID])

    assert result.exit_code == 0, result.output
    assert "web_search" in result.output
    assert "success" in result.output


def test_actions_list_status_filter(mocker):
    _patch_config(mocker)
    mock_client = _patch_client(mocker, {"items": [], "count": 0, "next_cursor": None})

    runner.invoke(app, ["actions", "list", _AGENT_ID, "--status", "error"])

    call_kwargs = mock_client.request.call_args
    assert "error" in str(call_kwargs)


def test_actions_list_json(mocker):
    _patch_config(mocker)
    data = {"items": [], "count": 0, "next_cursor": None}
    _patch_client(mocker, data)
    result = runner.invoke(app, ["actions", "list", _AGENT_ID, "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["count"] == 0


def test_actions_stats(mocker):
    _patch_config(mocker)
    _patch_client(mocker, {
        "total_actions": 150,
        "error_rate": 0.12,
        "avg_duration_ms": 280.5,
        "by_tool": [
            {"tool_name": "web_search", "count": 100, "avg_duration_ms": 300.0, "error_rate": 0.1},
            {"tool_name": "send_email", "count": 50, "avg_duration_ms": 250.0, "error_rate": 0.15},
        ],
    })

    result = runner.invoke(app, ["actions", "stats", _AGENT_ID])

    assert result.exit_code == 0, result.output
    assert "150" in result.output
    assert "web_search" in result.output
    assert "12.0%" in result.output


def test_actions_stats_json(mocker):
    _patch_config(mocker)
    data = {"total_actions": 5, "error_rate": 0.0, "avg_duration_ms": None, "by_tool": []}
    _patch_client(mocker, data)
    result = runner.invoke(app, ["actions", "stats", _AGENT_ID, "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["total_actions"] == 5


# ---------------------------------------------------------------------------
# export / import
# ---------------------------------------------------------------------------

def test_export_writes_file(mocker, tmp_path):
    _patch_config(mocker)
    export_data = json.dumps({"export_version": "1.0", "agent": {"name": "bot"}}).encode()
    out_file = str(tmp_path / "backup.json")

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_bytes.return_value = iter([export_data])
    mock_client.stream.return_value.__enter__ = lambda s: mock_resp
    mock_client.stream.return_value.__exit__ = MagicMock(return_value=False)

    mocker.patch("crewlayer.cli.client.get_client", return_value=mock_client)

    result = runner.invoke(app, ["export", _AGENT_ID, "--output", out_file])

    assert result.exit_code == 0, result.output
    assert Path(out_file).read_bytes() == export_data


def test_import_from_file(mocker, tmp_path):
    _patch_config(mocker)

    payload = {
        "export_version": "1.0",
        "agent": {"name": "bot"},
        "memories": [], "actions": [], "episodes": [],
        "sessions": [], "episode_memories": [], "relations": [],
    }
    import_file = tmp_path / "backup.json"
    import_file.write_text(json.dumps(payload))

    new_id = str(uuid.uuid4())
    _patch_client(mocker, {
        "agent": {
            "id": new_id, "name": "bot", "status": "idle", "tags": [],
            "config": {}, "current_session_id": None,
            "status_updated_at": "2024-01-01T00:00:00",
            "tenant_id": _TENANT_ID, "description": None,
        },
        "id_map": {"memories": {}, "actions": {}, "episodes": {}, "sessions": {}},
        "warnings": [],
    }, 201)

    result = runner.invoke(app, ["import", str(import_file)])

    assert result.exit_code == 0, result.output
    assert new_id in result.output
    assert "bot" in result.output


def test_import_missing_file(mocker):
    _patch_config(mocker)
    result = runner.invoke(app, ["import", "/nonexistent/backup.json"])
    assert result.exit_code == 1
    assert "File not found" in result.output or result.exit_code != 0


def test_import_invalid_json(mocker, tmp_path):
    _patch_config(mocker)
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not valid json {{")
    result = runner.invoke(app, ["import", str(bad_file)])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# config command
# ---------------------------------------------------------------------------

def test_config_show(mocker):
    mocker.patch(
        "crewlayer.cli.config.load",
        return_value={"url": "http://localhost:8000", "api_key": "crwl_abc123def456"},
    )
    mocker.patch("crewlayer.cli.config.config_path", return_value=Path("/home/user/.crewlayer/config.json"))

    result = runner.invoke(app, ["config"])

    assert result.exit_code == 0, result.output
    assert "http://localhost:8000" in result.output
    assert "crwl_abc123d" in result.output


def test_config_not_set(mocker):
    mocker.patch("crewlayer.cli.config.load", return_value={})
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# HTTP error handling
# ---------------------------------------------------------------------------

def test_api_error_shows_message(mocker):
    _patch_config(mocker)
    mock_client = MagicMock()
    mock_client.request.return_value = _mock_resp({"detail": "Agente no encontrado"}, 404)
    mocker.patch("crewlayer.cli.client.get_client", return_value=mock_client)

    result = runner.invoke(app, ["agents", "status", str(uuid.uuid4())])

    assert result.exit_code == 1


def test_connection_error_shows_message(mocker):
    import httpx

    _patch_config(mocker)
    mock_client = MagicMock()
    mock_client.request.side_effect = httpx.ConnectError("connection refused")
    mocker.patch("crewlayer.cli.client.get_client", return_value=mock_client)

    result = runner.invoke(app, ["agents", "list"])

    assert result.exit_code == 1
