# CrewLayer MCP Server

Exposes CrewLayer as an MCP (Model Context Protocol) server so Claude can interact
with agents, memory, actions, and shared context directly as tools.

## Available tools

| Tool | Description |
|------|-------------|
| `memory_recall` | Semantic search over an agent's long-term memories |
| `memory_append` | Append a message to short-term Redis memory |
| `memory_extract` | Close a session and extract long-term memories |
| `action_log` | Record a tool invocation as an immutable action |
| `action_list` | List actions for an agent with optional filters |
| `context_write` | Write a value to the shared blackboard |
| `context_read` | Read a value from the shared blackboard |
| `agent_status` | Get an agent's current runtime status |
| `agent_set_status` | Update an agent's runtime status |

## Prerequisites

- Python 3.12+
- `mcp[cli]` installed: `pip install "mcp[cli]>=1.27.2"`
- A running CrewLayer API (see the root `docker-compose.yml`)
- A valid CrewLayer API key

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CREWLAYER_API_KEY` | _(required)_ | API key to authenticate with CrewLayer |
| `CREWLAYER_BASE_URL` | `http://localhost:8000` | Base URL of the CrewLayer REST API |
| `MCP_TRANSPORT` | `stdio` | Transport: `stdio` for local, `sse` for HTTP/Docker |

---

## Claude Desktop

Add to `claude_desktop_config.json`
(macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`,
Windows: `%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "crewlayer": {
      "command": "python",
      "args": ["/absolute/path/to/CrewLayer/mcp/server.py"],
      "env": {
        "CREWLAYER_API_KEY": "crwl_your_key_here",
        "CREWLAYER_BASE_URL": "http://localhost:8000"
      }
    }
  }
}
```

Restart Claude Desktop after saving. The CrewLayer tools appear in the tool list.

---

## Claude Code

From the project root, run:

```bash
claude mcp add crewlayer \
  --command python \
  --args "mcp/server.py" \
  --env CREWLAYER_API_KEY=crwl_your_key_here \
  --env CREWLAYER_BASE_URL=http://localhost:8000
```

Or add a `.mcp.json` file at the project root:

```json
{
  "mcpServers": {
    "crewlayer": {
      "command": "python",
      "args": ["mcp/server.py"],
      "env": {
        "CREWLAYER_API_KEY": "crwl_your_key_here",
        "CREWLAYER_BASE_URL": "http://localhost:8000"
      }
    }
  }
}
```

---

## Docker (SSE transport)

The `mcp` service is included in `docker-compose.yml` and starts automatically:

```bash
docker compose up -d
```

The MCP server is then available at `http://localhost:8001/sse`.

To connect Claude Desktop to the Docker SSE server, update `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "crewlayer": {
      "command": "npx",
      "args": ["-y", "@anthropic-ai/mcp-client-cli", "http://localhost:8001/sse"]
    }
  }
}
```

---

## Automatic action logging

Every MCP tool call is automatically intercepted by the `@auto_log` decorator
in `server.py`. For each invocation it:

1. Sets the agent to **`working`** before execution.
2. Records the start timestamp.
3. Executes the tool.
4. Logs a CrewLayer action record (`POST /v1/agents/{id}/actions`) with
   `tool_name`, `input_params`, `output_result`, `duration_ms`, and
   `status` (`success` or `error`).
5. Sets the agent back to **`idle`** in a `finally` block.

This happens transparently — you do not need to call `action_log` for the
CrewLayer tools themselves. All errors are swallowed so a failed status update
never breaks the tool execution.

---

## System prompt for Claude Code (VS Code)

For Claude to use CrewLayer automatically on every task — loading memory at
the start, logging actions in the middle, and saving context at the end —
add the system prompt from [`mcp/INSTRUCTIONS.md`](INSTRUCTIONS.md) to Claude
Code.

### How to add it in VS Code

1. Open VS Code with the **Claude Code** extension installed.
2. Open the command palette (`Ctrl+Shift+P` / `Cmd+Shift+P`) and run
   **"Claude Code: Open Settings"**, or go to
   **File → Preferences → Settings** and search for **Claude Code**.
3. Find the **System Prompt** field (setting key: `claudeCode.systemPrompt`).
4. Paste the contents of [`mcp/INSTRUCTIONS.md`](INSTRUCTIONS.md) (the
   fenced code block, without the surrounding markdown).
5. Save settings. The prompt takes effect on the next Claude Code session.

> **Tip — project-scoped prompt via CLAUDE.md:** You can also paste the same
> content into your project's `CLAUDE.md` file under a `## Instructions` section.
> Claude Code reads `CLAUDE.md` automatically on every session in that project,
> so no VS Code setting is needed. This approach keeps the instructions version-
> controlled alongside the code.

---

## Running manually

```bash
# stdio (Claude Desktop / Claude Code):
CREWLAYER_API_KEY=crwl_your_key python mcp/server.py

# SSE (Docker / remote — binds to 0.0.0.0:8001):
CREWLAYER_API_KEY=crwl_your_key MCP_TRANSPORT=sse python mcp/server.py
```
