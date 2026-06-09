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

## Running manually

```bash
# stdio (Claude Desktop / Claude Code):
CREWLAYER_API_KEY=crwl_your_key python mcp/server.py

# SSE (Docker / remote — binds to 0.0.0.0:8001):
CREWLAYER_API_KEY=crwl_your_key MCP_TRANSPORT=sse python mcp/server.py
```
