# Life Dashboard — Architecture

## Production Overview

```
Browser
  │  HTTPS
  ▼
Global Load Balancer + IAP (Google login gate)
  │  signed X-Goog-IAP-JWT-Assertion header
  ▼
Cloud Run — life-dashboard (Flask, 1 worker, 8 threads)
  │
  ├── GCS: <project>-dashboard-data/dashboard.json  (private)
  └── Secret Manager: SECRET_KEY, API_KEY

Cloud Scheduler (06:00 Europe/Amsterdam)
  │  POST + OIDC token
  ▼
Cloud Function — bg-generator (gen2, 512 MB, 300s timeout)
  │
  ├── GCS: dashboard.json (read — events for prompt)
  ├── Open-Meteo API (weather code)
  ├── Gemini 2.5 Flash image generation (us-central1)
  └── GCS: <project>-dashboard-bg/backgrounds/YYYY-MM-DD.png (public)

Browser (on load)
  HEAD https://storage.googleapis.com/<BG_BUCKET>/backgrounds/<today>.png
  → 200: AI image as CSS background (clean, no overlay)
  → 404: static SVG forest scene fallback
```

---

## Local Development

```
Browser (HTML/CSS/JS)
        │  fetch() REST calls
        ▼
Flask dev server  (run.py → app/__init__.py)
        │
        ├─ auth.py     ← all auth disabled when API_KEY not set
        ├─ routes.py   ← /api/* CRUD + /mcp endpoint
        └─ database.py ← TinyDB open/close helpers
                              │
                        data/dashboard.json   (local file)
```

---

## Technology Choices

| Layer         | Technology          | Why                                                      |
|---------------|---------------------|----------------------------------------------------------|
| Server        | Flask 3.x           | Minimal, well-documented Python web framework            |
| Database      | TinyDB 4.x          | Document-store NoSQL; pure Python; stores as JSON        |
| Frontend      | Vanilla JS          | No build step, no framework overhead for a personal tool |
| Charts        | Chart.js 4 (CDN)    | Widely used, excellent docs, easy to customise           |
| Styling       | Custom CSS          | Full control; CSS variables make theming trivial         |
| Auth          | google-auth         | IAP JWT validation; API key fallback                     |
| BG generation | Gemini 2.5 Flash    | Isolated in Cloud Function — keeps web image lean        |

---

## Authentication (`app/auth.py`)

Four auth paths, checked in order:

1. **IAP JWT** — browser sessions via Load Balancer. `X-Goog-IAP-JWT-Assertion` header validated against Google's public keys. Requires `IAP_AUDIENCE` env var (`/projects/<num>/global/backendServices/<id>`).
2. **API key** — agents and scripts hitting the Cloud Run URL directly. `X-Api-Key` header matched against `API_KEY` env var (from Secret Manager).
3. **Google OAuth Bearer** — `Authorization: Bearer <token>` validated via Google's tokeninfo endpoint. Requires `ALLOWED_EMAIL` env var.
4. **Local dev** — all requests allowed when `API_KEY` is not set.

---

## Database Schema

TinyDB stores documents in named tables within a single JSON file.
Each document gets an auto-incrementing integer `doc_id` (exposed as `id` in the API).

### `tasks`
```json
{ "cat": "work | personal", "text": "string", "priority": "high | med | low", "due": "YYYY-MM-DD", "done": false }
```

### `events`
```json
{ "title": "string", "date": "YYYY-MM-DD", "time": "string", "cat": "work | personal" }
```

### `projects`
```json
{ "name": "string", "cat": "work | personal", "pct": 65, "deadline": "string", "color": "#hex" }
```

### `year_events`
```json
{ "title": "string", "q": "Q1 2026 (Jan–Mar) | …", "date": "string", "cat": "work | personal", "color": "#hex" }
```

### `holidays`
```json
{ "date": "YYYY-MM-DD", "title": "string", "cat": "holiday" }
```

### `recurring`
```json
{ "title": "string", "month": 1, "day": 15, "cat": "birthday | personal | …" }
```

### `gcal_events`

```json
{ "date": "YYYY-MM-DD", "title": "string", "time": "HH:MM | """, "cat": "personal", "gcal_id": "string" }
```

---

## REST API Contract

All endpoints require auth. Error responses: `{ "error": "message" }`.

```
GET    /api/<table>           200 → [ { id, ...fields }, … ]
POST   /api/<table>           201 → { id, ...fields }
PUT    /api/<table>/<id>      200 → { id, ...fields }
DELETE /api/<table>/<id>      200 → { "deleted": id }
POST   /api/holidays/sync     200 → { "synced": N, "years": [...] }
POST   /api/gcal/sync         200 → { "synced": N }
POST   /mcp                   JSON-RPC 2.0 — see MCP section below
```

Valid table names: `tasks`, `events`, `projects`, `year_events`, `holidays`, `recurring`, `gcal_events`

---

## MCP Endpoint (`POST /mcp`)

Implements the [Model Context Protocol](https://modelcontextprotocol.io) streamable HTTP transport (JSON-RPC 2.0). Exposes four tools: `list_items`, `create_item`, `update_item`, `delete_item`.

Used by Claude and other AI agents to read and write dashboard data. Also available as a standalone server (`mcp_server.py`) for local agent use.

---

## Frontend Architecture

`app.js` is structured as a simple state machine:

```
STATE (in-memory JS object)
  tasks / events / projects / year_events / holidays / recurring / gcal_events
  weekBgUrl   ← URL of today's AI background, or null for SVG fallback
  modal.{ table, id, defaults }

Boot flow:
  DOMContentLoaded → loadAll() → renderAll() → loadBackgroundImage()

loadBackgroundImage():
  HEAD https://storage.googleapis.com/<BG_BUCKET>/backgrounds/<today>.png
  → ok:  STATE.weekBgUrl = url; renderWeekPath()
  → err: SVG fallback (no change)

On user action (checkbox / edit / delete / save):
  1. Call API (fetch PUT/POST/DELETE)
  2. Update STATE in place
  3. Call renderAll() to re-draw everything
```

---

## Key Files

| File | Purpose |
|------|---------|
| `run.py` | Entry point; starts Flask dev server |
| `app/__init__.py` | App factory; wires up DB init + blueprint |
| `app/auth.py` | IAP JWT + API key + Bearer token auth |
| `app/database.py` | `get_db()`, GCS sync, seed functions |
| `app/routes.py` | All routes (SPA shell + REST API + MCP) |
| `app/templates/index.html` | HTML shell; loads CSS + JS |
| `app/static/style.css` | All styles (variables, layout, modal) |
| `app/static/app.js` | All frontend logic (state, render, API) |
| `functions/bg_generator/main.py` | Cloud Function: daily AI background generation |
| `data/dashboard.json` | TinyDB file (auto-created; gitignored) |
| `deploy/setup.sh` | One-time GCP infrastructure provisioning |

---

## Adding a New Tab

1. Add a `<button data-tab="my-tab">` in `index.html` nav
2. Add `<section id="tab-my-tab" class="tab-section">` in `index.html` main
3. If new data is needed, add a table in `database.py` and routes in `routes.py`
4. Add `STATE.my_items = []` in `app.js` STATE object
5. Add a fetch in `loadAll()` and a `renderMyTab()` called from `renderAll()`
