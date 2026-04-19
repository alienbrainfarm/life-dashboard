#!/usr/bin/env python3
"""
Life Dashboard MCP Server — mcp 1.x (FastMCP)

Tools:
  list_items(table)
  create_item(table, data)
  update_item(table, id, data)
  delete_item(table, id)

Credentials are resolved from env vars, falling back to the .env file.
"""

import json
import os
import ssl
import urllib.request
import urllib.error
from pathlib import Path

try:
    import certifi
    _ssl_ctx = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _ssl_ctx = None

from mcp.server.fastmcp import FastMCP


# ── Credentials ───────────────────────────────────────────────────────────────

def _load_env_file() -> dict:
    candidates = [
        Path(__file__).parent / ".env",                               # same dir as script
        Path.home() / "data" / "life-dashboard" / ".env",            # fallback
        Path(__file__).parent.parent.parent / "life-dashboard" / ".env",
    ]
    for path in candidates:
        if path.exists():
            result = {}
            for line in path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    result[k.strip()] = v.strip().strip('"').strip("'")
            return result
    return {}


_env = _load_env_file()

API_URL = (
    os.environ.get("DASHBOARD_API_URL")
    or _env.get("DASHBOARD_API_URL")
    or "http://127.0.0.1:5000"
)
API_KEY = (
    os.environ.get("DASHBOARD_API_KEY")
    or os.environ.get("API_KEY")
    or _env.get("DASHBOARD_API_KEY")
    or _env.get("API_KEY")
    or ""
)

VALID_TABLES = {"tasks", "events", "projects", "year_events", "holidays", "recurring"}


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _api(method: str, table: str, doc_id: int | None = None, data: dict | None = None):
    if table not in VALID_TABLES:
        return {"error": f"Unknown table '{table}'. Valid: {', '.join(sorted(VALID_TABLES))}"}
    url = f"{API_URL}/api/{table}"
    if doc_id is not None:
        url += f"/{doc_id}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={"X-Api-Key": API_KEY, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15, context=_ssl_ctx) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return {"error": json.loads(e.read())}
        except Exception:
            return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}


# ── MCP server ────────────────────────────────────────────────────────────────

mcp = FastMCP("life-dashboard")


@mcp.tool()
def list_items(table: str) -> str:
    """List all items in a dashboard table (tasks, events, projects, year_events, holidays, recurring)."""
    return json.dumps(_api("GET", table), indent=2, ensure_ascii=False)


@mcp.tool()
def create_item(table: str, data: dict) -> str:
    """Create a new item in a dashboard table.
    tasks: {cat, text, priority, due, done}.
    events: {date, title, cat, time}.
    projects: {name, cat, pct, deadline, color}.
    year_events: {q, title, cat, date, color}.
    holidays: {date (YYYY-MM-DD), title, cat}.
    recurring: {title, month (1-12), day (1-31), cat}.
    """
    return json.dumps(_api("POST", table, data=data), indent=2, ensure_ascii=False)


@mcp.tool()
def update_item(table: str, id: int, data: dict) -> str:
    """Update fields on an existing dashboard item by its id."""
    return json.dumps(_api("PUT", table, doc_id=id, data=data), indent=2, ensure_ascii=False)


@mcp.tool()
def delete_item(table: str, id: int) -> str:
    """Delete a dashboard item by its id."""
    return json.dumps(_api("DELETE", table, doc_id=id), indent=2, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="stdio")
