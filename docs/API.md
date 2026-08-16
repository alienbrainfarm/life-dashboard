# Life Dashboard — API Reference

The dashboard exposes a REST API for programmatic access by agents, scripts, and automation tools.

> **Note:** the hosted deployment was decommissioned on 2026-08-16 — the GCP project was
> deleted. The remote URLs below are no longer reachable. Running locally
> (`python run.py` → `http://127.0.0.1:5000`) is unaffected.

## Two access paths

| Caller | URL | Auth |
|--------|-----|------|
| Browser | `https://dashboard.your-domain.com` | Google login via IAP |
| Agent / script | `https://<cloudrun-url>.run.app` | `X-Api-Key` header |

The Cloud Run URL is printed at the end of `deploy/setup.sh`.
To look it up: `gcloud run services describe life-dashboard --region=europe-west4 --format="get(status.url)"`

To retrieve the API key:
```bash
gcloud secrets versions access latest --secret=dashboard-api-key --project=YOUR_PROJECT_ID
```

---

## Authentication

Include the key in every request:

```
X-Api-Key: <your-key>
```

Requests missing or supplying a wrong key receive `401 Unauthorized`.

---

## Tables

| Table | Contents |
|-------|----------|
| `tasks` | Action items (work / personal) |
| `events` | Calendar events with date and time |
| `projects` | Longer-running projects with % progress |
| `year_events` | 1–2 year roadmap items |
| `holidays` | Dutch public holidays (synced from Nager.Date) |
| `recurring` | Recurring events — birthdays etc. |
| `gcal_events` | Google Calendar events (read-only, synced via service account) |

---

## Endpoints

### List all items
```
GET /api/<table>
```
Returns an array of all documents. Each document includes an `id` field (integer, assigned by the database).

### Create an item
```
POST /api/<table>
Content-Type: application/json
```
Returns the created document with its assigned `id` and HTTP 201.

### Update an item
```
PUT /api/<table>/<id>
Content-Type: application/json
```
Replaces the document with the supplied fields. Returns the updated document.

### Delete an item
```
DELETE /api/<table>/<id>
```
Returns `{"deleted": <id>}`.

---

### Sync Dutch public holidays

```
POST /api/holidays/sync
Content-Type: application/json   (optional)
```

Body (optional): `{"years": [2026, 2027]}` — defaults to current and next year.
Returns `{"synced": N, "years": [...]}`.

---

### Sync Google Calendar
```
POST /api/gcal/sync
```
Fetches the next `GCAL_SYNC_DAYS` (default 60) days from Google Calendar using the service account identity. Clears and re-inserts `gcal_events`. Returns `{"synced": N}`.

---

## Document schemas

### tasks
```json
{
  "cat":      "work | personal",
  "text":     "Task description",
  "priority": "high | med | low",
  "due":      "YYYY-MM-DD",
  "done":     false
}
```

### events
```json
{
  "date":  "YYYY-MM-DD",
  "title": "Event name",
  "cat":   "work | personal",
  "time":  "10:00 AM | All day"
}
```

### projects
```json
{
  "name":     "Project name",
  "cat":      "work | personal",
  "pct":      42,
  "deadline": "Apr 2026",
  "color":    "#4f46e5"
}
```

### year_events
```json
{
  "q":     "Q2 2026 (Apr–Jun) | 2027 Horizon",
  "title": "Milestone name",
  "cat":   "work | personal",
  "date":  "Apr 2026",
  "color": "#4f46e5"
}
```

### holidays
```json
{
  "date":  "YYYY-MM-DD",
  "title": "Eerste Kerstdag",
  "cat":   "holiday"
}
```

### recurring

```json
{
  "title": "Mum's birthday",
  "month": 6,
  "day":   14,
  "cat":   "birthday"
}
```

### gcal_events *(read-only — managed by sync)*

```json
{
  "date":    "YYYY-MM-DD",
  "title":   "Event name",
  "time":    "14:30",
  "cat":     "personal",
  "gcal_id": "<google-calendar-event-id>"
}
```

---

## curl examples

```bash
BASE="https://<cloudrun-url>.run.app"
KEY="your-api-key"

# List tasks
curl -H "X-Api-Key: $KEY" "$BASE/api/tasks"

# Add a task
curl -X POST "$BASE/api/tasks" \
  -H "X-Api-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"cat":"work","text":"Review API docs","priority":"med","due":"2026-03-10","done":false}'

# Mark task 3 as done
curl -X PUT "$BASE/api/tasks/3" \
  -H "X-Api-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"done":true}'

# Delete task 3
curl -X DELETE "$BASE/api/tasks/3" \
  -H "X-Api-Key: $KEY"

# Add a project
curl -X POST "$BASE/api/projects" \
  -H "X-Api-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"Garden House Rebuild","cat":"personal","pct":5,"deadline":"Summer 2027","color":"#22d3ee"}'
```

---

## Using with Claude (Cowork / tool_use)

When giving Claude access to the dashboard API, provide the following tool definition in your system prompt or tool list. Replace the placeholder values.

```json
{
  "name": "dashboard",
  "description": "Read and update the life dashboard. Use this to add tasks, mark tasks done, add events, update project progress, or check what's on the roadmap. Always fetch current state before making changes.",
  "input_schema": {
    "type": "object",
    "properties": {
      "method": {
        "type": "string",
        "enum": ["GET", "POST", "PUT", "DELETE"],
        "description": "HTTP method"
      },
      "table": {
        "type": "string",
        "enum": ["tasks", "events", "projects", "year_events", "holidays", "recurring", "gcal_events"],
        "description": "Which collection to operate on"
      },
      "id": {
        "type": "integer",
        "description": "Document ID — required for PUT and DELETE"
      },
      "data": {
        "type": "object",
        "description": "Request body — required for POST and PUT"
      }
    },
    "required": ["method", "table"]
  }
}
```

Claude translates calls like `{"method":"POST","table":"tasks","data":{...}}` into:

```
POST https://<cloudrun-url>.run.app/api/tasks
X-Api-Key: <key>
Content-Type: application/json

{...}
```

### Example system prompt snippet

```
You have access to the life dashboard via the `dashboard` tool.
API base: https://<cloudrun-url>.run.app
API key:  <key>   (include as X-Api-Key header on every request)

When asked to add a task, event, or update a project, use the tool.
Fetch current state first when context matters (e.g. checking if a task exists).
```

---

## Local development

When running locally with Docker (no `API_KEY` env var set), **all `/api/*` requests are allowed without a key**. This keeps local dev frictionless.

```bash
# No key needed locally
curl http://localhost:8080/api/tasks
```
