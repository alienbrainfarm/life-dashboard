#!/usr/bin/env python3
"""
Sync Mac Calendar events to the Life Dashboard.

Reads directly from the Calendar SQLite database and pushes events
to the dashboard API, deduplicating by title+date.

Usage:
    python scripts/sync_calendar.py [--days 30] [--dry-run]
"""

import sqlite3
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
import urllib.request
import urllib.error

CALENDAR_DB = os.path.expanduser(
    "~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb"
)

# Calendars to skip when syncing
SKIP_CALENDARS = {
    "Birthdays",
    "Siri Suggestions",
    "Scheduled Reminders",
    "Found in Mail",
    "Found in Natural Language",
    "Facebook Birthdays",
}

# Apple's epoch offset: Jan 1 2001 → Jan 1 1970 = 978307200 seconds
APPLE_EPOCH_OFFSET = 978307200


def get_dashboard_url():
    from dotenv import load_dotenv
    load_dotenv()
    return os.getenv("DASHBOARD_URL", "http://127.0.0.1:5000")


def get_api_key():
    from dotenv import load_dotenv
    load_dotenv()
    return os.getenv("API_KEY", "")


def fetch_calendar_events(days: int) -> list[dict]:
    """Read upcoming events from the Mac Calendar SQLite database."""
    now_apple = time.time() - APPLE_EPOCH_OFFSET
    end_apple = now_apple + (days * 86400)

    conn = sqlite3.connect(f"file:{CALENDAR_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            ci.summary as title,
            datetime(ci.start_date + 978307200, 'unixepoch', 'localtime') as start_dt,
            datetime(ci.end_date + 978307200, 'unixepoch', 'localtime') as end_dt,
            c.title as calendar,
            ci.all_day
        FROM CalendarItem ci
        JOIN Calendar c ON ci.calendar_id = c.ROWID
        WHERE ci.start_date >= ?
          AND ci.start_date <= ?
          AND ci.summary IS NOT NULL
          AND ci.summary != ''
        ORDER BY ci.start_date
    """, (now_apple, end_apple))

    events = []
    seen = set()  # deduplicate by title+date

    for row in cur.fetchall():
        cal = row["calendar"]
        if cal in SKIP_CALENDARS:
            continue

        title = row["title"].strip()
        start = row["start_dt"]
        date = start[:10]  # YYYY-MM-DD
        time_str = start[11:16] if not row["all_day"] else ""

        key = (title.lower(), date)
        if key in seen:
            continue
        seen.add(key)

        events.append({
            "title": title,
            "date": date,
            "time": time_str,
            "cat": cal,
        })

    conn.close()
    return events


def get_existing_events(base_url: str, api_key: str) -> list[dict]:
    """Fetch current events from the dashboard API."""
    req = urllib.request.Request(
        f"{base_url}/api/events",
        headers={"X-API-Key": api_key},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def post_event(base_url: str, api_key: str, event: dict) -> dict:
    """Create a new event in the dashboard."""
    data = json.dumps(event).encode()
    req = urllib.request.Request(
        f"{base_url}/api/events",
        data=data,
        headers={
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def delete_event(base_url: str, api_key: str, event_id: int):
    """Delete an event from the dashboard."""
    req = urllib.request.Request(
        f"{base_url}/api/events/{event_id}",
        headers={"X-API-Key": api_key},
        method="DELETE",
    )
    urllib.request.urlopen(req)


def sync(days: int, dry_run: bool, replace: bool):
    base_url = get_dashboard_url()
    api_key = get_api_key()

    print(f"Fetching events from Mac Calendar (next {days} days)...")
    cal_events = fetch_calendar_events(days)
    print(f"  Found {len(cal_events)} events")

    print(f"Fetching existing events from dashboard ({base_url})...")
    existing = get_existing_events(base_url, api_key)

    deleted = 0
    if replace:
        # Determine the sync window date range
        today = datetime.now().date()
        end_date = today + timedelta(days=days)

        # Delete existing dashboard events that fall within the sync window
        to_delete = [
            e for e in existing
            if today <= datetime.strptime(e["date"], "%Y-%m-%d").date() <= end_date
        ]
        print(f"Deleting {len(to_delete)} existing events in sync window...")
        for e in to_delete:
            if dry_run:
                print(f"  [DRY RUN] Would delete: {e['date']} — {e['title']}")
            else:
                delete_event(base_url, api_key, e["id"])
                print(f"  Deleted: {e['date']} — {e['title']}")
            deleted += 1

        # After replace, existing_keys should be empty for the sync window
        # so all calendar events in the window will be added
        existing_keys = {}
    else:
        # Index existing by title+date for dedup
        existing_keys = {
            (e["title"].lower(), e["date"]): e
            for e in existing
        }

    added = 0
    skipped = 0

    for ev in cal_events:
        key = (ev["title"].lower(), ev["date"])
        if key in existing_keys:
            skipped += 1
            continue

        if dry_run:
            print(f"  [DRY RUN] Would add: {ev['date']} {ev['time']} — {ev['title']} ({ev['cat']})")
        else:
            post_event(base_url, api_key, ev)
            print(f"  Added: {ev['date']} {ev['time']} — {ev['title']} ({ev['cat']})")
        added += 1

    print(f"\nDone. Deleted: {deleted}, Added: {added}, Skipped (already exist): {skipped}")


def list_calendars():
    """Show what calendars and event counts are available."""
    conn = sqlite3.connect(f"file:{CALENDAR_DB}?mode=ro", uri=True)
    cur = conn.cursor()
    cur.execute("""
        SELECT c.title, COUNT(ci.ROWID) as cnt
        FROM Calendar c
        LEFT JOIN CalendarItem ci ON ci.calendar_id = c.ROWID
        GROUP BY c.ROWID
        ORDER BY cnt DESC
    """)
    print(f"{'Calendar':<35} {'Events':>6}")
    print("-" * 43)
    for row in cur.fetchall():
        skip = " (skipped)" if row[0] in SKIP_CALENDARS else ""
        print(f"{row[0]:<35} {row[1]:>6}{skip}")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync Mac Calendar → Life Dashboard")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    p_sync = subparsers.add_parser("sync", help="Sync events to dashboard")
    p_sync.add_argument("--days", type=int, default=30, help="Days ahead to sync (default: 30)")
    p_sync.add_argument("--dry-run", action="store_true", help="Show what would be added without writing")
    p_sync.add_argument("--replace", action="store_true", help="Delete existing dashboard events before syncing")

    p_list = subparsers.add_parser("calendars", help="List available calendars and event counts")

    args = parser.parse_args()

    if args.cmd == "calendars":
        list_calendars()
    elif args.cmd == "sync":
        sync(args.days, args.dry_run, args.replace)
