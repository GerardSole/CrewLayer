"""crewlayer tenants ..."""
import json
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel

from crewlayer.cli import client as _client

app = typer.Typer(help="Manage tenants.")
console = Console()


@app.command("create")
def create(
    name: Annotated[str, typer.Option("--name", help="Tenant name")],
    as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
) -> None:
    """Create a new tenant and print the bootstrap API key (shown once)."""
    with console.status("Creating tenant..."):
        data = _client.request("POST", "/v1/tenants", json={"name": name})

    if as_json:
        print(json.dumps(data, indent=2, default=str))
        return

    console.print(Panel.fit(
        f"[bold green]✓ Tenant created[/bold green]\n\n"
        f"  ID:              [cyan]{data['id']}[/cyan]\n"
        f"  Name:            {data['name']}\n"
        f"  Plan:            {data.get('plan', 'free')}\n\n"
        f"  [bold yellow]Initial API Key (save it — shown only once):[/bold yellow]\n"
        f"  [bold white]{data['initial_api_key']}[/bold white]",
        title="New Tenant",
        border_style="green",
    ))
