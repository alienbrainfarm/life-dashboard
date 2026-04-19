"""
Flask routes – serves the SPA shell, a REST JSON API, and an MCP endpoint.

REST API
--------
GET    /api/<table>           – list all documents
POST   /api/<table>           – create a document
PUT    /api/<table>/<id>      – replace a document
DELETE /api/<table>/<id>      – delete a document

MCP (Model Context Protocol) — streamable HTTP transport
---------------------------------------------------------
POST   /mcp                   – JSON-RPC 2.0 endpoint for AI agent tool use
       Supports: initialize, notifications/initialized, tools/list, tools/call

Both /api/* and /mcp require the X-Api-Key header (or an IAP browser session).

Valid tables: tasks | events | projects | year_events
"""

import json
import logging
import os
import urllib.request
from datetime import date, datetime, timezone, timedelta
from flask import Blueprint, jsonify, render_template, request, abort
from tinydb import TinyDB
from tinydb import Query
from .database import get_db
from .auth import api_authorized

logger = logging.getLogger(__name__)

main = Blueprint("main", __name__)

VALID_TABLES = {"tasks", "events", "projects", "year_events", "holidays", "recurring", "gcal_events"}


# ── API authentication ─────────────────────────────────────────────────────────

@main.before_request
def check_api_auth():
    """Guard all /api/* and /mcp routes with the auth check defined in auth.py."""
    if request.path.startswith("/api/") or request.path == "/mcp":
        if not api_authorized():
            return jsonify({"error": "Unauthorized – supply a valid X-Api-Key header"}), 401


# ── SPA shell ─────────────────────────────────────────────────────────────────

@main.route("/")
def index():
    bg_bucket = os.environ.get("BG_BUCKET", "")
    return render_template("index.html", bg_bucket=bg_bucket)


# ── Generic CRUD helpers ──────────────────────────────────────────────────────

def _all_docs(db: TinyDB, table: str) -> list[dict]:
    """Return all documents in a table, injecting their doc_id as 'id'."""
    return [{"id": doc.doc_id, **doc} for doc in db.table(table).all()]


def _require_table(table: str) -> None:
    if table not in VALID_TABLES:
        abort(404, description=f"Unknown table: {table}")


# ── API routes ────────────────────────────────────────────────────────────────

@main.route("/api/<table>", methods=["GET"])
def list_docs(table: str):
    _require_table(table)
    db = get_db()
    docs = _all_docs(db, table)
    db.close()
    return jsonify(docs)


@main.route("/api/<table>", methods=["POST"])
def create_doc(table: str):
    _require_table(table)
    data: dict = request.get_json(force=True)
    db = get_db()
    doc_id = db.table(table).insert(data)
    db.close()
    return jsonify({"id": doc_id, **data}), 201


@main.route("/api/<table>/<int:doc_id>", methods=["PUT"])
def update_doc(table: str, doc_id: int):
    _require_table(table)
    data: dict = request.get_json(force=True)
    db = get_db()
    tbl = db.table(table)
    if tbl.get(doc_id=doc_id) is None:
        db.close()
        abort(404, description=f"Document {doc_id} not found in {table}")
    tbl.update(data, doc_ids=[doc_id])
    updated = tbl.get(doc_id=doc_id)
    db.close()
    return jsonify({"id": doc_id, **updated})


@main.route("/api/<table>/<int:doc_id>", methods=["DELETE"])
def delete_doc(table: str, doc_id: int):
    _require_table(table)
    db = get_db()
    db.table(table).remove(doc_ids=[doc_id])
    db.close()
    return jsonify({"deleted": doc_id})


# ── Dutch holidays sync ────────────────────────────────────────────────────────

NAGER_URL = "https://date.nager.at/api/v3/PublicHolidays/{year}/NL"

@main.route("/api/holidays/sync", methods=["POST"])
def sync_holidays():
    """Fetch NL public holidays from Nager.Date and store them in TinyDB.

    Clears existing holidays for the requested years, then re-inserts.
    Body (optional): {"years": [2026, 2027]}  — defaults to current + next year.
    """
    body = request.get_json(force=True, silent=True) or {}
    current_year = date.today().year
    raw_years = body.get("years")

    if raw_years is None:
        years = [current_year, current_year + 1]
    else:
        if not isinstance(raw_years, list):
            abort(400, description="'years' must be a list of integers")

        normalized_years = []
        for y in raw_years:
            try:
                normalized_years.append(int(y))
            except (TypeError, ValueError):
                abort(400, description="'years' must contain only integers")

        # De-duplicate while preserving order
        seen = set()
        years = []
        for y in normalized_years:
            if y not in seen:
                seen.add(y)
                years.append(y)

        if not years:
            abort(400, description="'years' list cannot be empty")
    inserted = 0
    db = get_db()
    tbl = db.table("holidays")
    H = Query()

    for year in years:
        url = NAGER_URL.format(year=year)
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                holidays = json.loads(resp.read())
        except Exception as e:
            db.close()
            return jsonify({"error": f"Failed to fetch holidays for {year}: {e}"}), 502

        # Remove existing entries for this year before re-inserting
        tbl.remove(H.date.matches(f"^{year}-"))

        for h in holidays:
            tbl.insert({
                "date":  h["date"],        # "YYYY-MM-DD"
                "title": h["localName"],   # Dutch name
                "cat":   "holiday",
            })
            inserted += 1

    db.close()
    return jsonify({"synced": inserted, "years": years}), 200


# ── Google Calendar sync ───────────────────────────────────────────────────────

GCAL_CALENDAR_ID = os.environ.get("GCAL_CALENDAR_ID", "primary")
GCAL_SYNC_DAYS   = int(os.environ.get("GCAL_SYNC_DAYS", "60"))


@main.route("/api/gcal/sync", methods=["POST"])
def sync_gcal():
    """Fetch events from Google Calendar and store them in the gcal_events table.

    Uses the ambient service account identity (Cloud Run) or
    GOOGLE_APPLICATION_CREDENTIALS locally.  The calendar must be shared with
    the service account email.

    Clears all existing gcal_events, then re-inserts the next GCAL_SYNC_DAYS
    days of events.
    """
    try:
        import google.auth
        from googleapiclient.discovery import build

        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/calendar.readonly"]
        )
    except Exception as e:
        logger.error("GCal auth failed: %s", e)
        return jsonify({"error": f"Google auth failed: {e}"}), 502

    try:
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)

        now   = datetime.now(timezone.utc)
        until = now + timedelta(days=GCAL_SYNC_DAYS)

        result = service.events().list(
            calendarId=GCAL_CALENDAR_ID,
            timeMin=now.isoformat(),
            timeMax=until.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=250,
        ).execute()
    except Exception as e:
        logger.error("GCal API call failed: %s", e)
        return jsonify({"error": f"Google Calendar API error: {e}"}), 502

    db  = get_db()
    tbl = db.table("gcal_events")
    tbl.truncate()

    inserted = 0
    for item in result.get("items", []):
        start = item.get("start", {})
        # All-day events have "date"; timed events have "dateTime"
        if "dateTime" in start:
            dt     = datetime.fromisoformat(start["dateTime"])
            date_s = dt.date().isoformat()
            time_s = dt.strftime("%H:%M")
        else:
            date_s = start.get("date", "")
            time_s = ""

        tbl.insert({
            "date":    date_s,
            "title":   item.get("summary", "(no title)"),
            "time":    time_s,
            "cat":     "personal",
            "gcal_id": item.get("id", ""),
        })
        inserted += 1

    db.close()
    return jsonify({"synced": inserted}), 200


# ── MCP endpoint (streamable HTTP transport) ──────────────────────────────────

MCP_TOOLS = [
    {
        "name": "list_items",
        "description": "List all items in a dashboard table. Returns an array with each item's id and fields.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "enum": ["tasks", "events", "projects", "year_events", "holidays", "recurring"],
                    "description": "The table to list",
                }
            },
            "required": ["table"],
        },
    },
    {
        "name": "create_item",
        "description": (
            "Create a new item in a dashboard table. "
            "tasks: {cat, text, priority, due, done}. "
            "events: {date, title, cat, time}. "
            "projects: {name, cat, pct, deadline, color}. "
            "year_events: {q, title, cat, date, color}. "
            "holidays: {date (YYYY-MM-DD), title, cat}. "
            "recurring: {title, month (1-12), day (1-31), cat}."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "enum": ["tasks", "events", "projects", "year_events", "holidays", "recurring"]},
                "data": {"type": "object", "description": "Fields for the new item"},
            },
            "required": ["table", "data"],
        },
    },
    {
        "name": "update_item",
        "description": "Update one or more fields on an existing item by its id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "enum": ["tasks", "events", "projects", "year_events", "holidays", "recurring"]},
                "id": {"type": "integer", "description": "Document id"},
                "data": {"type": "object", "description": "Fields to update"},
            },
            "required": ["table", "id", "data"],
        },
    },
    {
        "name": "delete_item",
        "description": "Delete an item by its id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "enum": ["tasks", "events", "projects", "year_events", "holidays", "recurring"]},
                "id": {"type": "integer", "description": "Document id"},
            },
            "required": ["table", "id"],
        },
    },
]


def _mcp_tool_call(name: str, arguments: dict):
    """Execute an MCP tool call and return the result dict."""
    table = arguments.get("table", "")
    if table not in VALID_TABLES:
        return {"error": f"Unknown table '{table}'"}

    if name == "list_items":
        db = get_db()
        result = _all_docs(db, table)
        db.close()
        return result

    elif name == "create_item":
        data = arguments.get("data", {})
        db = get_db()
        doc_id = db.table(table).insert(data)
        db.close()
        return {"id": doc_id, **data}

    elif name == "update_item":
        doc_id = arguments.get("id")
        data = arguments.get("data", {})
        db = get_db()
        tbl = db.table(table)
        if tbl.get(doc_id=doc_id) is None:
            db.close()
            return {"error": f"Document {doc_id} not found in {table}"}
        tbl.update(data, doc_ids=[doc_id])
        updated = tbl.get(doc_id=doc_id)
        db.close()
        return {"id": doc_id, **updated}

    elif name == "delete_item":
        doc_id = arguments.get("id")
        db = get_db()
        db.table(table).remove(doc_ids=[doc_id])
        db.close()
        return {"deleted": doc_id}

    return {"error": f"Unknown tool: {name}"}


@main.route("/mcp", methods=["POST"])
def mcp():
    """MCP streamable HTTP transport endpoint."""
    body = request.get_json(force=True, silent=True) or {}
    rpc_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})

    def ok(result):
        return jsonify({"jsonrpc": "2.0", "id": rpc_id, "result": result})

    def err(code, message):
        return jsonify({"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}})

    if method == "initialize":
        return ok({
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "life-dashboard", "version": "0.2.0"},
        })

    if method == "notifications/initialized":
        return "", 204

    if method == "tools/list":
        return ok({"tools": MCP_TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        result = _mcp_tool_call(tool_name, tool_args)
        return ok({"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]})

    if method == "ping":
        return ok({})

    return err(-32601, f"Method not found: {method}")


# ── Error handlers ────────────────────────────────────────────────────────────

@main.app_errorhandler(404)
def not_found(err):
    return jsonify({"error": str(err)}), 404


@main.app_errorhandler(400)
def bad_request(err):
    return jsonify({"error": str(err)}), 400
