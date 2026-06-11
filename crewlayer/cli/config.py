"""Config file management: ~/.crewlayer/config.json"""
import json
from pathlib import Path
from typing import Any

_DIR = Path.home() / ".crewlayer"
_FILE = _DIR / "config.json"


def load() -> dict[str, Any]:
    if not _FILE.exists():
        return {}
    try:
        return json.loads(_FILE.read_text())
    except Exception:
        return {}


def save(url: str, api_key: str) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    _FILE.write_text(json.dumps({"url": url.rstrip("/"), "api_key": api_key}, indent=2))
    _FILE.chmod(0o600)


def url() -> str:
    return load().get("url", "http://localhost:8000")


def api_key() -> str | None:
    return load().get("api_key")


def config_path() -> Path:
    return _FILE
