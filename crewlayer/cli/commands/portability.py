"""crewlayer export / import (agent portability)."""
import json
import os
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from crewlayer.cli import client as _client

console = Console()


def export_agent(
    agent_id: Annotated[str, typer.Argument(help="Agent UUID to export")],
    output: Annotated[
        str,
        typer.Option("--output", "-o", help="Output file path"),
    ] = "",
) -> None:
    """Export a full agent backup to a JSON file."""
    dest = output or f"agent_{agent_id[:8]}.json"

    with console.status(f"Exporting agent {agent_id[:8]}... (this may take a moment for large agents)"):
        _client.stream_to_file(f"/v1/agents/{agent_id}/export", dest)

    size_kb = os.path.getsize(dest) / 1024
    console.print(f"[green]✓[/green] Exported to [bold]{dest}[/bold] ({size_kb:.1f} KB)")


def import_agent(
    file: Annotated[str, typer.Argument(help="Path to the .json export file")],
    as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
) -> None:
    """Import an agent from an export file (creates a new agent with a new ID)."""
    path = Path(file)
    if not path.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        console.print(f"[red]Invalid JSON: {exc}[/red]")
        raise typer.Exit(1)

    with console.status("Importing agent..."):
        data = _client.request("POST", "/v1/agents/import", json=payload)

    if as_json:
        print(json.dumps(data, indent=2, default=str))
        return

    agent = data.get("agent", {})
    id_map = data.get("id_map", {})
    warnings = data.get("warnings", [])

    console.print(f"[green]✓[/green] Agent imported as [bold]{agent.get('name')}[/bold]")
    console.print(f"  New ID: [cyan]{agent.get('id')}[/cyan]")
    console.print(f"  Memories remapped:  {len(id_map.get('memories', {}))}")
    console.print(f"  Actions remapped:   {len(id_map.get('actions', {}))}")
    console.print(f"  Episodes remapped:  {len(id_map.get('episodes', {}))}")
    if agent.get("tags"):
        console.print(f"  Tags: {', '.join(agent['tags'])}")
    for w in warnings:
        console.print(f"  [yellow]⚠ {w}[/yellow]")
