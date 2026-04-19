#!/usr/bin/env python3
"""
Local prompt preview for bg_generator.

Reads dashboard.json from the cloud GCS bucket, fetches today's weather,
assembles and prints the Imagen prompt — no Imagen call, no cost.

Run with the project root venv (has google-cloud-storage):
    source venv/bin/activate
    python functions/bg_generator/preview_prompt.py

Requires GCP application-default credentials:
    gcloud auth application-default login
"""

import json
import os
import re
import urllib.request
from datetime import date, timedelta
from pathlib import Path

# Load .env from project root (optional — falls back to env vars already set)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parents[2] / ".env")
except ImportError:
    pass

GCS_BUCKET  = os.environ.get("GCS_BUCKET", "")
GCP_PROJECT = os.environ.get("GCP_PROJECT", "")

if not GCS_BUCKET:
    raise SystemExit("ERROR: GCS_BUCKET not set. Add it to .env or export it.")


# ── Load events from GCS ──────────────────────────────────────────────────────

def _load_events(today: date) -> list[dict]:
    from google.cloud import storage as gcs_lib
    week_end = today + timedelta(days=7)
    client   = gcs_lib.Client()
    raw      = client.bucket(GCS_BUCKET).blob("dashboard.json").download_as_text()
    data     = json.loads(raw)

    events          = list(data.get("events",    {}).values())
    holidays        = list(data.get("holidays",  {}).values())
    recurring_items = list(data.get("recurring", {}).values())
    tasks           = list(data.get("tasks",     {}).values())

    result = []

    for e in events:
        try:
            d = date.fromisoformat(e["date"])
            if today <= d < week_end:
                result.append({"date": e["date"], "title": e.get("title", "")})
        except (KeyError, ValueError):
            pass

    for h in holidays:
        try:
            d = date.fromisoformat(h["date"])
            if today <= d < week_end:
                result.append({"date": h["date"], "title": h.get("title", "")})
        except (KeyError, ValueError):
            pass

    for t in tasks:
        try:
            if t.get("done"):
                continue
            d = date.fromisoformat(t["due"])
            if today <= d < week_end:
                result.append({"date": t["due"], "title": t.get("text", "")})
        except (KeyError, ValueError):
            pass

    for r in recurring_items:
        try:
            month, day = int(r["month"]), int(r["day"])
            candidate  = date(today.year, month, day)
            if candidate < today:
                candidate = date(today.year + 1, month, day)
            if today <= candidate < week_end:
                result.append({"date": candidate.isoformat(), "title": r.get("title", "")})
        except (KeyError, ValueError):
            pass

    return result


# ── Seasonal elements ─────────────────────────────────────────────────────────

def _seasonal_elements(month: int) -> str:
    if month in (12, 1, 2):
        return "bare branches, frost on ground, grey-blue winter light"
    elif month in (3, 4):
        return "cherry blossoms, tulips, fresh green shoots, soft spring light"
    elif month in (5, 6):
        return "wildflowers, lush canopy, long warm light"
    elif month in (7, 8):
        return "full summer foliage, golden afternoon haze"
    elif month in (9, 10):
        return "orange and red autumn leaves, misty morning"
    else:  # 11
        return "fallen leaves, bare branches, low golden light"


# ── Weather descriptor ────────────────────────────────────────────────────────

def _weather_descriptor(wmo_code: int) -> str:
    if wmo_code <= 1:
        return "clear blue sky, warm sunlight"
    elif wmo_code <= 3:
        return "partly cloudy, soft diffused light"
    elif wmo_code <= 48:
        return "misty fog between the trees"
    elif wmo_code <= 67:
        return "light rain, wet path, puddles reflecting sky"
    elif wmo_code <= 77:
        return "light snow dusting the branches"
    elif wmo_code <= 82:
        return "rain showers, dramatic clouds"
    else:
        return "stormy, dark clouds, dramatic light"


# ── Path winding ──────────────────────────────────────────────────────────────

def _winding_descriptor(event_count: int) -> str:
    if event_count <= 2:
        return "gently curving, peaceful"
    elif event_count <= 5:
        return "winding"
    else:
        return "twisting and turning through dense forest,"


# ── Visual props from event titles ────────────────────────────────────────────

VISUAL_PROPS = [
    (r'birthday',                           'people celebrating a birthday with a cake and balloons'),
    (r'music|band|guitar|practice|jam|gig', 'a small group of musicians sitting in a circle playing guitars'),
    (r'meeting|work|client|call',           'a group of people having an outdoor meeting around a table'),
    (r'holiday',                            'colourful bunting strung between the trees, festive atmosphere'),
    (r'run|jog|5k|sport|gym',              'a runner on the path ahead'),
    (r'dentist|doctor|medical',             'a first aid kit open on a tree stump'),
    (r'dinner|lunch|restaurant',            'people dining together at a rustic outdoor table with lanterns'),
]

# Proximity labels: nearest event appears closest to the viewer
_PROXIMITY = ['just beside the path in the foreground', 'further along the path', 'in the distance']


def _visual_props(events: list[dict]) -> str:
    found = []
    seen_props = set()
    for event in sorted(events, key=lambda e: e.get("date", "")):
        title = event.get("title", "").lower()
        for pattern, prop in VISUAL_PROPS:
            if re.search(pattern, title) and prop not in seen_props:
                proximity = _PROXIMITY[min(len(found), len(_PROXIMITY) - 1)]
                found.append(f"{prop} {proximity}")
                seen_props.add(prop)
                break
        if len(found) >= 3:
            break
    return ', '.join(found) if found else 'a wooden milestone marker beside the path'


# ── Weather fetch ─────────────────────────────────────────────────────────────

def _fetch_weather_code() -> int:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=52.3676&longitude=4.9041"
        "&daily=weathercode&timezone=Europe%2FAmsterdam&forecast_days=1"
    )
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read())
            return int(data["daily"]["weathercode"][0])
    except Exception:
        return 2  # partly cloudy fallback


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(events: list[dict], today: date) -> tuple[str, str]:
    wmo = _fetch_weather_code()

    prompt = (
        f"A {_winding_descriptor(len(events))} dirt path through a Dutch forest, "
        f"{_seasonal_elements(today.month)}, "
        f"{_weather_descriptor(wmo)}. "
        f"Scattered near the path: {_visual_props(events)}. "
        "Photorealistic DSLR photograph, natural light, shallow depth of field, "
        "ultra-detailed, 8K. Wide landscape format."
    )
    negative = (
        "text, words, letters, signs, signposts, people, animals, logos, watermark, "
        "painting, illustration, watercolour, cartoon, drawing, sketch, render"
    )
    return prompt, negative


# ── Image generation (optional) ───────────────────────────────────────────────

def _generate_image(prompt: str, negative: str, out_path: str):
    import vertexai
    from vertexai.preview.vision_models import ImageGenerationModel

    print("\nCalling Vertex AI Imagen 3 ...")
    vertexai.init(project=GCP_PROJECT, location="us-central1")
    model  = ImageGenerationModel.from_pretrained("imagen-3.0-generate-002")
    images = model.generate_images(
        prompt=prompt,
        negative_prompt=negative,
        number_of_images=1,
        aspect_ratio="16:9",
    )
    images[0].save(out_path)
    print(f"Saved → {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    generate = "--generate" in sys.argv

    today = date.today()
    print(f"Fetching events from gs://{GCS_BUCKET}/dashboard.json ...")
    events = _load_events(today)

    print(f"\nDate: {today}  |  Events in next 7 days: {len(events)}")
    for e in sorted(events, key=lambda x: x["date"]):
        print(f"  {e['date']}: {e['title']}")

    print("\nFetching weather ...")
    prompt, negative = _build_prompt(events, today)

    print("\n" + "=" * 60)
    print("PROMPT")
    print("=" * 60)
    print(prompt)
    print("\n" + "=" * 60)
    print("NEGATIVE PROMPT")
    print("=" * 60)
    print(negative)

    if generate:
        out = f"/tmp/bg_preview_{today.isoformat()}.png"
        _generate_image(prompt, negative, out)
        import subprocess
        subprocess.run(["open", out])  # opens in Preview on macOS
