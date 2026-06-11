"""crewlayer agents ..."""
import json
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from crewlayer.cli import client as _client

app = typer.Typer(help="Manage agents.")
console = Console()

_STATUS_COLOR = {"idle": "green", "working": "yellow", "error": "red"}


@app.command("list")
def list_agents(
    tags: Annotated[
        Optional[str],
        typer.Option("--tags", help="Filter by tags (comma-separated, AND logic)"),
    ] = None,
    status: Annotated[
        Optional[str],
        typer.Option("--status", help="Filter by status (idle/working/error)"),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
) -> None:
    """List all agents for the current tenant."""
    params: dict = {}
    if tags:
        params["tags"] = tags
    if status:
        params["status"] = status

    with console.status("Fetching agents..."):
        data = _client.request("GET", "/v1/agents", params=params or None)

    if as_json:
        print(json.dumps(data, indent=2, default=str))
        return

    if not data:
        console.print("[dim]No agents found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
    table.add_column("ID", style="dim", min_width=36)
    table.add_column("Name", style="bold")
    table.add_column("Status", min_width=8)
    table.add_column("Tags")

    for a in data:
        st = a.get("status", "idle")
        color = _STATUS_COLOR.get(st, "white")
        table.add_row(
            a["id"],
            a["name"],
            f"[{color}]{st}[/{color}]",
            ", ".join(a.get("tags") or []) or "-",
        )

    console.print(table)
    console.print(f"\n[dim]{len(data)} agent(s)[/dim]")


@app.command("create")
def create(
    name: Annotated[str, typer.Option("--name", help="Agent name")],
    description: Annotated[Optional[str], typer.Option("--description")] = None,
    tags: Annotated[
        Optional[str],
        typer.Option("--tags", help="Comma-separated tags"),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
) -> None:
    """Create a new agent."""
    body: dict = {"name": name}
    if description:
        body["description"] = description
    if tags:
        body["tags"] = [t.strip() for t in tags.split(",") if t.strip()]

    with console.status("Creating agent..."):
        data = _client.request("POST", "/v1/agents", json=body)

    if as_json:
        print(json.dumps(data, indent=2, default=str))
        return

    console.print(f"[green]✓[/green] Agent [bold]{data['name']}[/bold] created")
    console.print(f"  ID:   [cyan]{data['id']}[/cyan]")
    if data.get("tags"):
        console.print(f"  Tags: {', '.join(data['tags'])}")


@app.command("status")
def agent_status(
    agent_id: Annotated[str, typer.Argument(help="Agent UUID")],
    as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
) -> None:
    """Get the current status of an agent (Redis-cached)."""
    with console.status("Fetching status..."):
        data = _client.request("GET", f"/v1/agents/{agent_id}/status")

    if as_json:
        print(json.dumps(data, indent=2, default=str))
        return

    st = data.get("status", "idle")
    color = _STATUS_COLOR.get(st, "white")
    console.print(f"Agent:   [cyan]{agent_id}[/cyan]")
    console.print(f"Status:  [{color}]{st}[/{color}]")
    if data.get("current_session_id"):
        console.print(f"Session: {data['current_session_id']}")
    if data.get("updated_at"):
        console.print(f"Updated: [dim]{data['updated_at'][:19].replace('T', ' ')}[/dim]")
