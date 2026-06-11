"""crewlayer actions ..."""
import json
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from crewlayer.cli import client as _client

app = typer.Typer(help="Query action history.")
console = Console()

_STATUS_COLOR = {"success": "green", "error": "red", "pending": "yellow"}


@app.command("list")
def list_actions(
    agent_id: Annotated[str, typer.Argument(help="Agent UUID")],
    status: Annotated[
        Optional[str],
        typer.Option("--status", help="Filter by status (success/error/pending)"),
    ] = None,
    tool: Annotated[
        Optional[str],
        typer.Option("--tool", help="Filter by tool name"),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 20,
    as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
) -> None:
    """List action history for an agent."""
    params: dict = {"limit": limit}
    if status:
        params["status"] = status
    if tool:
        params["tool_name"] = tool

    with console.status("Fetching actions..."):
        data = _client.request(
            "GET", f"/v1/agents/{agent_id}/actions", params=params
        )

    if as_json:
        print(json.dumps(data, indent=2, default=str))
        return

    items = data.get("items", [])
    count = data.get("count", len(items))

    if not items:
        console.print("[dim]No actions found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
    table.add_column("ID", style="dim", min_width=36)
    table.add_column("Tool", style="bold")
    table.add_column("Status", min_width=8)
    table.add_column("ms", justify="right", style="dim")
    table.add_column("Timestamp", style="dim")

    for a in items:
        st = a.get("status", "")
        color = _STATUS_COLOR.get(st, "white")
        ms = str(a["duration_ms"]) if a.get("duration_ms") is not None else "-"
        table.add_row(
            a["id"],
            a.get("tool_name", "-"),
            f"[{color}]{st}[/{color}]",
            ms,
            _fmt_dt(a.get("timestamp")),
        )

    console.print(table)
    console.print(f"\n[dim]{len(items)} of {count} action(s)[/dim]")


@app.command("stats")
def stats(
    agent_id: Annotated[str, typer.Argument(help="Agent UUID")],
    as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
) -> None:
    """Show aggregate stats for an agent's action history."""
    with console.status("Fetching stats..."):
        data = _client.request("GET", f"/v1/agents/{agent_id}/actions/stats")

    if as_json:
        print(json.dumps(data, indent=2, default=str))
        return

    total = data.get("total_actions", 0)
    err_rate = data.get("error_rate", 0.0)
    avg_ms = data.get("avg_duration_ms")

    err_color = "red" if err_rate >= 0.5 else "yellow" if err_rate >= 0.2 else "green"

    console.print(f"Total actions:  [bold]{total}[/bold]")
    console.print(f"Error rate:     [{err_color}]{err_rate * 100:.1f}%[/{err_color}]")
    if avg_ms is not None:
        console.print(f"Avg duration:   {avg_ms:.0f} ms")

    by_tool = data.get("by_tool", [])
    if by_tool:
        console.print()
        table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
        table.add_column("Tool", style="bold")
        table.add_column("Calls", justify="right")
        table.add_column("Avg ms", justify="right", style="dim")
        table.add_column("Error %", justify="right")

        for t in sorted(by_tool, key=lambda x: x.get("count", 0), reverse=True):
            er = t.get("error_rate", 0.0)
            er_color = "red" if er >= 0.5 else "yellow" if er >= 0.2 else "green"
            avg = t.get("avg_duration_ms")
            table.add_row(
                t.get("tool_name", "-"),
                str(t.get("count", 0)),
                f"{avg:.0f}" if avg is not None else "-",
                f"[{er_color}]{er * 100:.1f}%[/{er_color}]",
            )
        console.print(table)


def _fmt_dt(val: str | None) -> str:
    if not val:
        return "-"
    return val[:19].replace("T", " ")
