"""CrewLayer CLI — main entry point.

Install:  pip install crewlayer[cli]
Run:      crewlayer --help
"""
import json
from typing import Annotated

import typer
from rich.console import Console

from crewlayer.cli import config as _cfg
from crewlayer.cli.commands import actions, agents, keys, memory, portability, tenants

app = typer.Typer(
    name="crewlayer",
    help="Official CLI for the CrewLayer AI agent backend.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Sub-command groups
app.add_typer(tenants.app, name="tenants")
app.add_typer(keys.app, name="keys")
app.add_typer(agents.app, name="agents")
app.add_typer(memory.app, name="memory")
app.add_typer(actions.app, name="actions")

# Top-level export / import (registered as standalone commands)
app.command("export")(portability.export_agent)
app.command("import")(portability.import_agent)

console = Console()
err_console = Console(stderr=True)


@app.command("init")
def init() -> None:
    """Interactive wizard to configure the API URL and key.

    Saves credentials to [bold]~/.crewlayer/config.json[/bold].
    """
    console.print("[bold]CrewLayer Setup Wizard[/bold]")
    console.rule(style="dim")

    current = _cfg.load()
    default_url = current.get("url", "http://localhost:8000")
    default_key = current.get("api_key", "")

    url = typer.prompt(
        "API base URL",
        default=default_url,
    ).strip().rstrip("/")

    api_key = typer.prompt(
        "API key",
        default=default_key,
        hide_input=True,
    ).strip()

    # Quick connection test
    console.print()
    with console.status("Testing connection..."):
        import httpx

        try:
            resp = httpx.Client(
                base_url=url, headers={"X-API-Key": api_key}, timeout=10
            ).get("/v1/api-keys")
            ok = resp.status_code < 500
        except Exception:
            ok = False

    if ok:
        console.print("[green]✓ Connection OK[/green]")
    else:
        console.print("[yellow]⚠ Could not verify connection — saving anyway[/yellow]")

    _cfg.save(url, api_key)
    console.print(f"\n[dim]Config saved to {_cfg.config_path()}[/dim]")


@app.command("config")
def show_config(
    as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
) -> None:
    """Show the current configuration (key is masked)."""
    cfg = _cfg.load()
    if not cfg:
        console.print("[dim]Not configured. Run [bold]crewlayer init[/bold] first.[/dim]")
        raise typer.Exit(1)

    if as_json:
        masked = {**cfg, "api_key": cfg.get("api_key", "")[:12] + "..." if cfg.get("api_key") else ""}
        print(json.dumps(masked, indent=2))
        return

    key = cfg.get("api_key", "")
    masked_key = (key[:12] + "...") if key else "[red]not set[/red]"
    console.print(f"URL:     {cfg.get('url', 'not set')}")
    console.print(f"API key: {masked_key}")
    console.print(f"File:    [dim]{_cfg.config_path()}[/dim]")
