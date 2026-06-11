"""crewlayer keys ..."""
import json
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from crewlayer.cli import client as _client

app = typer.Typer(help="Manage API keys.")
console = Console()


@app.command("create")
def create(
    name: Annotated[str, typer.Option("--name", help="Key name / label")],
    scopes: Annotated[
        Optional[str],
        typer.Option("--scopes", help="Comma-separated scopes, e.g. memory:read,memory:write"),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
) -> None:
    """Create a new API key for the authenticated tenant (key shown once)."""
    body: dict = {"name": name}
    if scopes:
        body["scopes"] = [s.strip() for s in scopes.split(",") if s.strip()]

    with console.status("Creating API key..."):
        data = _client.request("POST", "/v1/api-keys", json=body)

    if as_json:
        print(json.dumps(data, indent=2, default=str))
        return

    scope_str = ", ".join(data.get("scopes") or []) or "[dim]all[/dim]"
    console.print(Panel.fit(
        f"[bold green]✓ API key created[/bold green]\n\n"
        f"  ID:      [cyan]{data['id']}[/cyan]\n"
        f"  Name:    {data['name']}\n"
        f"  Scopes:  {scope_str}\n\n"
        f"  [bold yellow]Key (save it — shown only once):[/bold yellow]\n"
        f"  [bold white]{data['key']}[/bold white]",
        title="New API Key",
        border_style="green",
    ))


@app.command("list")
def list_keys(
    as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
) -> None:
    """List all API keys for the current tenant."""
    with console.status("Fetching keys..."):
        data = _client.request("GET", "/v1/api-keys")

    if as_json:
        print(json.dumps(data, indent=2, default=str))
        return

    if not data:
        console.print("[dim]No API keys found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
    table.add_column("ID", style="dim", min_width=36)
    table.add_column("Name", style="bold")
    table.add_column("Scopes")
    table.add_column("Last used", style="dim")
    table.add_column("Expires", style="dim")

    for k in data:
        table.add_row(
            k["id"],
            k["name"],
            ", ".join(k.get("scopes") or []) or "all",
            _fmt_dt(k.get("last_used_at")),
            _fmt_dt(k.get("expires_at")) or "never",
        )

    console.print(table)
    console.print(f"\n[dim]{len(data)} key(s)[/dim]")


def _fmt_dt(val: str | None) -> str:
    if not val:
        return "-"
    return val[:19].replace("T", " ")
