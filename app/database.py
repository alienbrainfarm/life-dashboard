"""
TinyDB database layer.

Supports two storage backends, selected by environment variable:

  Local (default)
    Reads/writes  data/dashboard.json  on disk.
    Used when running locally with `python run.py`.

  Google Cloud Storage
    Reads/writes  dashboard.json  in a GCS bucket.
    Activated when the environment variable GCS_BUCKET is set.
    Used in production (Cloud Run).

Tables
------
tasks       – action items (work / personal)
events      – calendar events with date/time
projects    – longer-running projects with % progress
year_events – items on the 1-2 year roadmap
"""

import json
import os
from pathlib import Path

from tinydb import TinyDB

# ── Storage configuration ──────────────────────────────────────────────────────

DB_PATH = Path(__file__).parent.parent / "data" / "dashboard.json"
GCS_BUCKET = os.environ.get("GCS_BUCKET")
GCS_BLOB = "dashboard.json"


class GCSStorage:
    """
    TinyDB-compatible storage backend backed by a GCS object.

    On every read() the latest JSON is fetched from GCS.
    On every write() the JSON is pushed back to GCS.
    This is fine for a low-traffic personal dashboard.
    """

    def __init__(self, bucket_name: str, blob_name: str):
        from google.cloud import storage as gcs_lib
        client = gcs_lib.Client()
        self._bucket = client.bucket(bucket_name)
        self._blob_name = blob_name

    def read(self) -> dict | None:
        blob = self._bucket.blob(self._blob_name)
        if not blob.exists():
            return None
        return json.loads(blob.download_as_text(encoding="utf-8"))

    def write(self, data: dict) -> None:
        blob = self._bucket.blob(self._blob_name)
        blob.upload_from_string(
            json.dumps(data, indent=2, ensure_ascii=False),
            content_type="application/json",
        )

    def close(self) -> None:
        pass  # No persistent connection to close


def get_db() -> TinyDB:
    """Return an open TinyDB instance using the appropriate storage backend."""
    if GCS_BUCKET:
        return TinyDB(storage=GCSStorage, bucket_name=GCS_BUCKET, blob_name=GCS_BLOB)
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        return TinyDB(DB_PATH, indent=2)


def init_db() -> None:
    """Seed the database with sample data only if it is completely empty."""
    db = get_db()

    if len(db.table("tasks")) == 0:
        _seed_tasks(db)
    if len(db.table("events")) == 0:
        _seed_events(db)
    if len(db.table("projects")) == 0:
        _seed_projects(db)
    if len(db.table("year_events")) == 0:
        _seed_year_events(db)

    db.close()


# ── Seed helpers ──────────────────────────────────────────────────────────────

def _seed_tasks(db: TinyDB) -> None:
    db.table("tasks").insert_multiple([
        {"cat": "work",     "text": "Prepare Q1 strategy presentation",     "priority": "high", "due": "2026-03-04", "done": False},
        {"cat": "work",     "text": "Review and respond to client proposal", "priority": "high", "due": "2026-03-01", "done": False},
        {"cat": "work",     "text": "Weekly team standup notes",             "priority": "med",  "due": "2026-02-28", "done": True },
        {"cat": "work",     "text": "Update project tracker spreadsheet",    "priority": "med",  "due": "2026-03-05", "done": False},
        {"cat": "work",     "text": "Schedule performance reviews",          "priority": "low",  "due": "2026-03-10", "done": False},
        {"cat": "work",     "text": "Finish onboarding doc for new hire",    "priority": "high", "due": "2026-03-03", "done": False},
        {"cat": "personal", "text": "Book flights for summer holiday",       "priority": "high", "due": "2026-03-07", "done": False},
        {"cat": "personal", "text": "Sort through wardrobe / donate items",  "priority": "low",  "due": "2026-03-15", "done": False},
        {"cat": "personal", "text": "Call parents this weekend",             "priority": "med",  "due": "2026-03-01", "done": False},
        {"cat": "personal", "text": "Plan birthday dinner for Alex",         "priority": "med",  "due": "2026-03-12", "done": False},
    ])


def _seed_events(db: TinyDB) -> None:
    db.table("events").insert_multiple([
        {"date": "2026-03-01", "title": "Client Kick-off Call",        "cat": "work",     "time": "10:00 AM"},
        {"date": "2026-03-03", "title": "Alex's Birthday Dinner",      "cat": "personal", "time": "7:00 PM" },
        {"date": "2026-03-07", "title": "5K Run — Local Park",         "cat": "personal", "time": "8:00 AM" },
        {"date": "2026-03-10", "title": "Quarterly Business Review",   "cat": "work",     "time": "2:00 PM" },
        {"date": "2026-03-22", "title": "Team Off-site Workshop",      "cat": "work",     "time": "9:00 AM" },
        {"date": "2026-03-28", "title": "End of Quarter Review",       "cat": "work",     "time": "3:00 PM" },
        {"date": "2026-04-05", "title": "Home Renovation Starts",      "cat": "personal", "time": "All day" },
        {"date": "2026-05-20", "title": "Conference — Industry Summit","cat": "work",     "time": "All day" },
        {"date": "2026-07-10", "title": "Summer Holiday Departure",    "cat": "personal", "time": "All day" },
    ])


def _seed_projects(db: TinyDB) -> None:
    db.table("projects").insert_multiple([
        {"name": "Launch New Website",      "cat": "work",     "pct": 65, "deadline": "Apr 2026", "color": "#4f46e5"},
        {"name": "Home Kitchen Renovation", "cat": "personal", "pct": 10, "deadline": "Jun 2026", "color": "#ec4899"},
        {"name": "Complete Online Course",  "cat": "personal", "pct": 40, "deadline": "May 2026", "color": "#8b5cf6"},
        {"name": "Team Restructure Plan",   "cat": "work",     "pct": 80, "deadline": "Mar 2026", "color": "#0ea5e9"},
    ])


def _seed_year_events(db: TinyDB) -> None:
    db.table("year_events").insert_multiple([
        {"q": "Q1 2026 (Jan–Mar)", "title": "Q1 Planning Complete",       "cat": "work",     "date": "Mar 2026",     "color": "#4f46e5"},
        {"q": "Q1 2026 (Jan–Mar)", "title": "Team Workshop Off-site",      "cat": "work",     "date": "Mar 2026",     "color": "#4f46e5"},
        {"q": "Q2 2026 (Apr–Jun)", "title": "Website Launch",              "cat": "work",     "date": "Apr 2026",     "color": "#4f46e5"},
        {"q": "Q2 2026 (Apr–Jun)", "title": "Kitchen Renovation",          "cat": "personal", "date": "Apr–Jun 2026", "color": "#ec4899"},
        {"q": "Q2 2026 (Apr–Jun)", "title": "Industry Summit Conference",  "cat": "work",     "date": "May 2026",     "color": "#4f46e5"},
        {"q": "Q2 2026 (Apr–Jun)", "title": "Complete Online Course",      "cat": "personal", "date": "May 2026",     "color": "#8b5cf6"},
        {"q": "Q3 2026 (Jul–Sep)", "title": "Summer Holiday ✈",            "cat": "personal", "date": "Jul 2026",     "color": "#ec4899"},
        {"q": "Q3 2026 (Jul–Sep)", "title": "Mid-Year Performance Review", "cat": "work",     "date": "Jul 2026",     "color": "#4f46e5"},
        {"q": "Q4 2026 (Oct–Dec)", "title": "Annual Planning Session",     "cat": "work",     "date": "Oct 2026",     "color": "#4f46e5"},
        {"q": "Q4 2026 (Oct–Dec)", "title": "Holiday Travel",              "cat": "personal", "date": "Dec 2026",     "color": "#ec4899"},
        {"q": "2027 Horizon",      "title": "Promotion / Career Review",   "cat": "work",     "date": "Q1 2027",      "color": "#4f46e5"},
        {"q": "2027 Horizon",      "title": "International Trip",           "cat": "personal", "date": "2027",         "color": "#ec4899"},
    ])
