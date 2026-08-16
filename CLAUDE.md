# Life Dashboard — Project Instructions

## What This Is
Personal Flask dashboard. Single-page app with TinyDB backend. Python/Flask backend, vanilla JS frontend (no framework).

## Infrastructure

**Decommissioned on 2026-08-16 — there is no live deployment.** The GCP project backing this
app was deleted, along with Cloud Run, the load balancer, the `bg-generator` Cloud Function,
the daily Cloud Scheduler job, and all GCS buckets. The GitHub Actions deploy/teardown
workflows have been removed.

Treat the app as **local-only** (see *Running Locally* below). Storage falls back to TinyDB at
`data/dashboard.json`; the GCS backend in `app/database.py` is inert without `GCS_BUCKET` set.
Do not reference production URLs or suggest deploying unless the infrastructure is rebuilt.

`docs/DEPLOY.md` and `deploy/setup.sh` are kept as a reference for rebuilding from scratch.

## Key Files
| File | Purpose |
|------|---------|
| `run.py` | Entry point — `python run.py` |
| `app/__init__.py` | Flask app factory |
| `app/auth.py` | IAP JWT + API key + Bearer token auth |
| `app/routes.py` | REST API + SPA shell + MCP endpoint |
| `app/database.py` | TinyDB + GCS storage backend |
| `app/static/app.js` | All frontend logic (fetch, render, CRUD) |
| `app/static/style.css` | All styles (CSS variables) |
| `app/templates/index.html` | Single-page shell (Jinja2) |
| `functions/bg_generator/main.py` | Cloud Function — daily AI background image |
| `mcp_server.py` | MCP server exposing dashboard CRUD as tools |
| `.env` | API key and credentials (not committed) |

## Running Locally
```bash
source venv/bin/activate
python run.py
# → http://127.0.0.1:5000
```

## Data Model (TinyDB tables)
- `tasks` — `{cat, text, priority, due, done}`
- `events` — `{date, title, cat, time}`
- `projects` — `{name, cat, pct, deadline, color}`
- `year_events` — `{q, title, cat, date, color}`
- `holidays` — `{date, title, cat}` — synced from Nager.Date API
- `recurring` — `{title, month, day, cat}` — birthdays etc.
- `gcal_events` — `{date, title, time, cat, gcal_id}` — synced from Google Calendar (read-only)

## REST API Pattern
`GET/POST /api/<table>` and `PUT/DELETE /api/<table>/<id>` — same shape for all tables.
Also: `POST /api/holidays/sync`, `POST /api/gcal/sync`, and `POST /mcp` (JSON-RPC 2.0).

## Google Calendar sync

- `POST /api/gcal/sync` fetches the next `GCAL_SYNC_DAYS` (default 60) days from Google Calendar
- Uses ambient service account identity in Cloud Run (no extra credentials needed)
- Locally: set `GOOGLE_APPLICATION_CREDENTIALS` to a service account key file
- Calendar to sync: `GCAL_CALENDAR_ID` env var (default `primary`)
- **One-time setup:** share your Google Calendar with the Cloud Run service account email, and enable the Calendar API on your GCP project
- `gcal_events` are read-only in the UI — no edit/delete buttons

## This Week tab layout
- Background image (AI-generated or static SVG forest fallback) renders clean — no overlays
- Below the image: 7-day card strip (`renderWeekPath` in `app.js`) — today through today+6
- Day cards use `DAY_COLORS` (keyed by `getDay()`, 0=Sun…6=Sat) for the header band
- Today's card gets a `box-shadow` accent ring via `.day-card.today`
- CSS classes: `.week-bg`, `.week-strip`, `.day-card`, `.day-card-header`, `.day-card-body`, `.day-card-date`, `.day-card-item`

## Conventions

- **Always update documentation alongside code changes.** When adding or changing a feature, update `CLAUDE.md`, `README.md`, and any relevant files in `docs/` (especially `API.md`, `ARCHITECTURE.md`, `HOW_IT_WORKS.md`) in the same PR.
- Keep it simple — no JS framework, no ORM, no build step
- CSS variables in `:root` for theming
- All frontend state managed in `app.js`; no shared state libraries
- Modal configs defined in `MODAL_CONFIGS` in `app.js`
- Python dependencies in `requirements.txt`; use the existing `venv`
- Heavy ML deps (aiplatform, Pillow) live only in `functions/bg_generator/requirements.txt`

## Deploying
Push to `main` triggers GitHub Actions. See `docs/DEPLOY.md` for first-time setup.
