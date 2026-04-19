# Daily Background Generator

Generates a daily AI photorealistic background for the Week Path view using
Gemini 2.5 Flash (image generation). Runs as a standalone **Cloud Function**
triggered at 6 AM Amsterdam time via Cloud Scheduler.

## Architecture

```
Cloud Scheduler (06:00 Europe/Amsterdam)
    → POST https://<FUNCTION_URL>  (OIDC token — Cloud Run IAM)
        → download dashboard.json from GCS (private data bucket)
        → collect 7-day events / tasks / holidays / recurring items
        → fetch today's weather code from Open-Meteo (Amsterdam, no key)
        → build prompt  →  call Gemini 2.5 Flash image generation (us-central1)
        → upload PNG to gs://<BG_BUCKET>/backgrounds/YYYY-MM-DD.png
          (public read, Cache-Control: no-cache)

Browser (on load)
    → HEAD https://storage.googleapis.com/<BG_BUCKET>/backgrounds/<today>.png
    → 200: CSS background-image on week-grid, SVG signs overlay on top
    → 404: static SVG forest scene (fallback)
```

The web app (Cloud Run) has **no knowledge of Gemini** — heavy ML deps live
only in the Cloud Function. This keeps the web image lean and cold starts fast.

## GCS buckets

| Bucket | Contents | Access |
|--------|----------|--------|
| `<PROJECT_ID>-dashboard-data` | `dashboard.json` (TinyDB) | Private — SA only |
| `<PROJECT_ID>-dashboard-bg` | `backgrounds/YYYY-MM-DD.png` | Public read |

Background images are AI-generated landscapes with no personal data, so
public read is safe. The data bucket stays private.

Images are uploaded with `Cache-Control: no-cache` to prevent the GCS CDN
from serving stale versions after daily regeneration.

## Files

| File | Purpose |
|------|---------|
| `functions/bg_generator/main.py` | Cloud Function entry point |
| `functions/bg_generator/preview_prompt.py` | Local prompt preview + test image generation |
| `functions/bg_generator/requirements.txt` | Heavy deps (google-genai, Pillow) isolated here |
| `deploy/generate_bg.sh` | Script to trigger on-demand image generation |

## Authentication

The function accepts two auth methods:

| Caller | Method |
|--------|--------|
| Cloud Scheduler | OIDC token (`Authorization: Bearer`) — Cloud Run IAM verifies it |
| `generate_bg.sh` / agents | `X-Api-Key` header |

Cloud Run's `--no-allow-unauthenticated` ensures all requests are authenticated
at the infrastructure level before reaching the function code.

## Prompt structure

The prompt is assembled from live data each morning:

1. **Month** → seasonal elements: tulips (Mar–Apr), wildflowers (May–Jun), autumn leaves (Sep–Oct), frost (Dec–Feb), etc.
2. **WMO weather code** → atmosphere: sunny / misty / rainy / snowy / stormy
3. **Event/task titles** → Gemini is asked to place physical objects or small scenes beside the path representing each event, sorted by date (soonest = foreground, latest = distance). Gemini chooses the visual interpretation itself based on the event title.

Style: **photorealistic DSLR photograph**, shallow depth of field, 8K, 16:9.
No people, animals, text, signs, or logos.

## Local prompt preview

Iterate on the prompt without deploying:

```bash
source venv/bin/activate
python functions/bg_generator/preview_prompt.py           # print prompt only
python functions/bg_generator/preview_prompt.py --generate  # generate + open PNG
```

Reads live data from the cloud GCS bucket. Requires:
- `gcloud auth application-default login`
- `GCS_BUCKET`, `BG_BUCKET`, `GCP_PROJECT`, `GOOGLE_CLOUD_API_KEY` in `.env`

## Triggering manually

```bash
# Easiest — uses .env credentials
./deploy/generate_bg.sh

# Via Cloud Scheduler (uses OIDC, same as the daily run)
gcloud scheduler jobs run daily-bg-generate \
  --location=europe-west1 --project=YOUR_PROJECT_ID
```

## Deployment

The function is deployed by the GitHub Actions deploy workflow (manual `workflow_dispatch`
trigger), alongside the Cloud Run service. No manual CLI deploy needed for code changes.

For a fresh setup, everything is handled by `deploy/setup.sh` Phase 11.

## Setup (Phase 11 in isolation)

```bash
PROJECT_ID=your-gcp-project-id
REGION=europe-west4
SA_EMAIL=life-dashboard-sa@${PROJECT_ID}.iam.gserviceaccount.com
BUCKET_NAME=${PROJECT_ID}-dashboard-data
BG_BUCKET_NAME=${PROJECT_ID}-dashboard-bg
API_SECRET_NAME=dashboard-api-key

# Create public bg bucket
gcloud storage buckets create gs://${BG_BUCKET_NAME} \
  --location=${REGION} --project=${PROJECT_ID} \
  --no-uniform-bucket-level-access
gcloud storage buckets add-iam-policy-binding gs://${BG_BUCKET_NAME} \
  --member="allUsers" --role="roles/storage.objectViewer"
gcloud storage buckets add-iam-policy-binding gs://${BG_BUCKET_NAME} \
  --member="serviceAccount:${SA_EMAIL}" --role="roles/storage.objectAdmin"

# Deploy Cloud Function
gcloud functions deploy bg-generator \
  --gen2 --runtime=python312 --region=${REGION} \
  --source=functions/bg_generator \
  --entry-point=generate_background \
  --trigger-http --no-allow-unauthenticated \
  --service-account=${SA_EMAIL} \
  --set-env-vars="GCS_BUCKET=${BUCKET_NAME},BG_BUCKET=${BG_BUCKET_NAME},GCP_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_API_KEY=${GOOGLE_CLOUD_API_KEY}" \
  --update-secrets="API_KEY=${API_SECRET_NAME}:latest" \
  --memory=512Mi --timeout=300s --project=${PROJECT_ID}

FUNCTION_URL=$(gcloud functions describe bg-generator \
  --region=${REGION} --format="get(serviceConfig.uri)" --project=${PROJECT_ID})

# Create scheduler job (OIDC auth — no API key needed)
# Note: Cloud Scheduler uses europe-west1; europe-west4 is not supported
gcloud scheduler jobs create http daily-bg-generate \
  --location=europe-west1 --schedule="0 6 * * *" \
  --time-zone="Europe/Amsterdam" \
  --uri="${FUNCTION_URL}" \
  --http-method=POST \
  --oidc-service-account-email="${SA_EMAIL}" \
  --oidc-token-audience="${FUNCTION_URL}" \
  --attempt-deadline=300s --project=${PROJECT_ID}
```
