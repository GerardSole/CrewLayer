"""crewlayer memory ..."""
import json
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.rule import Rule
from rich.table import Table

from crewlayer.cli import client as _client

app = typer.Typer(help="Query agent memory.")
console = Console()


@app.command("recall")
def recall(
    agent_id: Annotated[str, typer.Argument(help="Agent UUID")],
    query: Annotated[str, typer.Argument(help="Semantic search query")],
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max results")] = 10,
    min_similarity: Annotated[
        float,
        typer.Option("--min-similarity", help="Minimum cosine similarity (0–1)"),
    ] = 0.0,
    as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
) -> None:
    """Semantic recall — find memories similar to the query."""
    body = {"query": query, "limit": limit, "min_similarity": min_similarity}

    with console.status("Recalling memories..."):
        data = _client.request(
            "POST", f"/v1/agents/{agent_id}/memory/recall", json=body
        )

    if as_json:
        print(json.dumps(data, indent=2, default=str))
        return

    results = data.get("results", [])
    console.print(f'[bold]Query:[/bold] "{query}"')
    console.print(Rule(style="dim"))

    if not results:
        console.print("[dim]No memories found.[/dim]")
        return

    for i, m in enumerate(results, 1):
        sim = m.get("similarity")
        sim_str = f"[cyan]{sim:.3f}[/cyan]" if sim is not None else ""
        imp = m.get("importance", 0.0)
        imp_color = "green" if imp >= 0.7 else "yellow" if imp >= 0.4 else "dim"
        content = m.get("content", "")
        tags = ", ".join(m.get("tags") or [])

        console.print(
            f"[dim]{i}.[/dim] {sim_str}  "
            f"[{imp_color}]importance={imp:.2f}[/{imp_color}]"
            + (f"  [dim]{tags}[/dim]" if tags else "")
        )
        console.print(f"   {content}")
        console.print()

    console.print(f"[dim]{len(results)} result(s)[/dim]")


@app.command("list")
def list_memories(
    agent_id: Annotated[str, typer.Argument(help="Agent UUID")],
    limit: Annotated[int, typer.Option("--limit", "-n", help="Page size")] = 20,
    page: Annotated[int, typer.Option("--page")] = 1,
    include_archived: Annotated[
        bool, typer.Option("--archived", help="Include archived memories")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
) -> None:
    """List memories for an agent (paginated)."""
    params: dict[str, Any] = {"page": page, "page_size": limit}
    if include_archived:
        params["include_archived"] = "true"

    with console.status("Fetching memories..."):
        data = _client.request(
            "GET", f"/v1/agents/{agent_id}/memory", params=params
        )

    if as_json:
        print(json.dumps(data, indent=2, default=str))
        return

    items = data.get("items", [])
    total = data.get("total", len(items))

    if not items:
        console.print("[dim]No memories found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
    table.add_column("ID", style="dim", min_width=36)
    table.add_column("Content", max_width=60)
    table.add_column("Importance", justify="right")
    table.add_column("Status", style="dim")
    table.add_column("Created", style="dim")

    for m in items:
        imp = m.get("importance", 0.0)
        imp_color = "green" if imp >= 0.7 else "yellow" if imp >= 0.4 else "dim"
        content = m.get("content", "")
        if len(content) > 57:
            content = content[:57] + "…"
        table.add_row(
            m["id"],
            content,
            f"[{imp_color}]{imp:.2f}[/{imp_color}]",
            m.get("status", "active"),
            _fmt_dt(m.get("created_at")),
        )

    console.print(table)
    console.print(f"\n[dim]Showing {len(items)} of {total} memories (page {page})[/dim]")


def _fmt_dt(val: str | None) -> str:
    if not val:
        return "-"
    return val[:10]
