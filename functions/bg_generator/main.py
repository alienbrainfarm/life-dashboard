"""
Cloud Function: generate_background

Reads dashboard.json from GCS, builds a prompt from the next 7 days of events,
generates a 16:9 Vertex AI Imagen background, and uploads it to the public bg bucket.

Triggered by Cloud Scheduler at 06:00 Europe/Amsterdam via HTTP POST.
Auth: X-Api-Key header checked against API_KEY env var.
"""

import json
import os
import tempfile
import urllib.request
from datetime import date, timedelta

import functions_framework
from google.cloud import storage as gcs_lib

GCS_BUCKET        = os.environ["GCS_BUCKET"]   # private data bucket (dashboard.json)
BG_BUCKET         = os.environ["BG_BUCKET"]    # public bg bucket (backgrounds/*.png)
GCP_PROJECT       = os.environ.get("GCP_PROJECT", "")
API_KEY           = os.environ.get("API_KEY", "")
GOOGLE_CLOUD_API_KEY = os.environ.get("GOOGLE_CLOUD_API_KEY", "")


# ── Auth ──────────────────────────────────────────────────────────────────────

def _check_auth(request) -> bool:
    # Accept Cloud Scheduler / service-to-service calls authenticated via OIDC.
    # Cloud Run verifies the Bearer token before the request reaches this code,
    # so its presence means the caller has already been authenticated by IAM.
    if request.headers.get("Authorization", "").startswith("Bearer "):
        return True
    # Also accept direct calls with the API key (agents, generate_bg.sh, etc.)
    if not API_KEY:
        return False
    return request.headers.get("X-Api-Key") == API_KEY


# ── Read dashboard data from GCS ─────────────────────────────────────────────

def _load_events(today: date) -> list[dict]:
    """Download dashboard.json from GCS and return all events in the next 7 days."""
    week_end = today + timedelta(days=7)
    client   = gcs_lib.Client()
    raw      = client.bucket(GCS_BUCKET).blob("dashboard.json").download_as_text()
    data     = json.loads(raw)

    # TinyDB stores tables as {"_default": {}, "events": {"1": {...}, "2": {...}}, ...}
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
        return "cherry blossoms, snowdrops, crocus, daffodils, tulips, fresh green shoots, soft spring light"
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


# ── Open-Meteo weather fetch ──────────────────────────────────────────────────

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

def _build_prompt(events: list[dict], today: date) -> str:
    wmo = _fetch_weather_code()
    season = _seasonal_elements(today.month)
    weather = _weather_descriptor(wmo)

    event_lines = [
        f"{date.fromisoformat(e['date']).strftime('%a %-d %b')}: {e['title']}"
        for e in sorted(events, key=lambda e: e.get("date", ""))
        if e.get("title")
    ]

    events_clause = ""
    if event_lines:
        events_clause = (
            f" Beside the path, place physical objects or small scenes that visually represent"
            f" this week's events ({', '.join(event_lines)}) — one prop per event,"
            " positioned along the path from foreground to distance."
            " Choose the objects yourself based on the event title."
        )

    prompt = (
        f"A winding dirt path through a Dutch forest, {season}, {weather}."
        f"{events_clause}"
        " Photorealistic DSLR photograph, natural light, shallow depth of field,"
        " ultra-detailed, 8K. Wide landscape format."
        " Do not include: text, words, letters, signs, signposts, people, animals,"
        " logos, watermarks, paintings, illustrations, cartoons, or sketches."
    )
    print(f"[bg_generator] prompt: {prompt}")
    return prompt


# ── Gemini image generation + GCS upload ─────────────────────────────────────

def _generate_and_upload(events: list[dict], today: date) -> str:
    """Generate image with Gemini, upload to GCS, return public URL."""
    from google import genai
    from google.genai import types

    prompt = _build_prompt(events, today)

    client = genai.Client(
        vertexai=True,
        project=GCP_PROJECT,
        location="us-central1",
        api_key=GOOGLE_CLOUD_API_KEY or None,
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash-image",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio="16:9",
                output_mime_type="image/png",
            ),
        ),
    )

    image_bytes = None
    for part in response.candidates[0].content.parts:
        if part.inline_data:
            image_bytes = part.inline_data.data  # already bytes in google-genai SDK
            break

    if not image_bytes:
        raise RuntimeError("Gemini returned no image in response")

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = tmp.name

    gcs_client = gcs_lib.Client()
    blob_name  = f"backgrounds/{today.isoformat()}.png"
    blob       = gcs_client.bucket(BG_BUCKET).blob(blob_name)
    blob.cache_control = "no-cache"
    blob.upload_from_filename(tmp_path, content_type="image/png")
    os.unlink(tmp_path)

    return f"https://storage.googleapis.com/{BG_BUCKET}/{blob_name}"


# ── Entry point ───────────────────────────────────────────────────────────────

@functions_framework.http
def generate_background(request):
    if not _check_auth(request):
        return ("Unauthorized", 401, {})

    today = date.today()
    try:
        events  = _load_events(today)
        url     = _generate_and_upload(events, today)
        return (json.dumps({"date": today.isoformat(), "url": url}),
                200, {"Content-Type": "application/json"})
    except Exception as exc:
        return (json.dumps({"error": str(exc)}),
                500, {"Content-Type": "application/json"})
