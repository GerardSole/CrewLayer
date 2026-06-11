"""Sync HTTP client wrapper around httpx."""
from typing import Any

import httpx
import typer
from rich.console import Console

from crewlayer.cli import config as _cfg

_err = Console(stderr=True)


def get_client(api_key: str | None = None) -> httpx.Client:
    key = api_key or _cfg.api_key()
    headers: dict[str, str] = {}
    if key:
        headers["X-API-Key"] = key
    return httpx.Client(base_url=_cfg.url(), headers=headers, timeout=30.0)


def request(
    method: str,
    path: str,
    *,
    api_key: str | None = None,
    **kwargs: Any,
) -> Any:
    """Make a synchronous API request.  Prints an error and exits on failure."""
    try:
        resp = get_client(api_key).request(method, path, **kwargs)
    except httpx.ConnectError:
        _err.print(f"[red]Cannot connect to {_cfg.url()}. Is the server running?[/red]")
        raise typer.Exit(1)
    except httpx.TimeoutException:
        _err.print("[red]Request timed out.[/red]")
        raise typer.Exit(1)

    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        _err.print(f"[red]{resp.status_code}: {detail}[/red]")
        raise typer.Exit(1)

    return None if resp.status_code == 204 else resp.json()


def stream_to_file(path: str, dest: str) -> None:
    """Stream a GET response to *dest* without loading everything into memory."""
    client = get_client()
    try:
        with client.stream("GET", path) as resp:
            if resp.status_code >= 400:
                _err.print(f"[red]{resp.status_code}: server error during export[/red]")
                raise typer.Exit(1)
            with open(dest, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=8192):
                    f.write(chunk)
    except httpx.ConnectError:
        _err.print(f"[red]Cannot connect to {_cfg.url()}.[/red]")
        raise typer.Exit(1)
