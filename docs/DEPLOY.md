# Deploying to GCP (Cloud Run + IAP)

## Architecture

```
GitHub Actions (manual workflow_dispatch)
    │
    ├──── Workload Identity Federation ──▶ GCP
    │                (keyless auth, no stored keys)
    ▼
Artifact Registry (container image)
    │
    ▼
Cloud Run (life-dashboard)  ◀── Global Load Balancer ◀── IAP ◀── Your browser
    │
    ├── GCS: <project>-dashboard-data/dashboard.json  (private)
    └── Secret Manager: SECRET_KEY, API_KEY

Cloud Scheduler (06:00 Amsterdam) ──OIDC──▶ Cloud Function (bg-generator)
    │                                              │
    │                                    Gemini 2.5 Flash (image generation)
    │                                              │
    └──────────────────────────────────▶ GCS: <project>-dashboard-bg/ (public)
```

- **Cloud Run** — runs the Flask app; scales to zero when idle
- **GCS (data)** — stores `dashboard.json`, survives container restarts
- **GCS (bg)** — stores AI-generated background PNGs; public read, no personal data
- **Load Balancer** — required to front Cloud Run with IAP
- **IAP** — Google login gate; only your account can access the dashboard URL
- **Cloud Function** — generates daily background image; heavy ML deps isolated here
- **Cloud Scheduler** — triggers the function at 06:00 Amsterdam time daily

---

## One-time manual step: OAuth Consent Screen

IAP requires an OAuth consent screen. This cannot be scripted — do it once in the Console:

1. Go to **APIs & Services → OAuth consent screen** in your GCP project
2. Choose **Internal** (since it's just for your own Google account)
3. Fill in App name, User support email, Developer contact
4. Click **Save and Continue** (no scopes needed)

Do this before running `setup.sh`.

---

## First deployment

1. Copy `.env.example` to `.env` and fill in your values:
   ```bash
   cp .env.example .env
   # edit: PROJECT_ID, REGION, DOMAIN, IAP_USER, GITHUB_REPO
   ```

2. Run the setup script from the project root:
   ```bash
   chmod +x deploy/setup.sh
   ./deploy/setup.sh
   ```

   The script runs 11 phases:
   | Phase | What it does |
   |-------|-------------|
   | 1 | Enable GCP APIs |
   | 2 | Create service account + IAM roles |
   | 3 | Create data GCS bucket, upload dashboard.json |
   | 4 | Create Flask SECRET_KEY in Secret Manager |
   | 5 | Build and push container image |
   | 6 | Deploy Cloud Run service |
   | 7 | Set up Load Balancer + SSL cert |
   | 8 | Enable IAP + set `IAP_AUDIENCE` env var on Cloud Run |
   | 9 | Configure Workload Identity Federation for GitHub Actions |
   | 10 | Generate API key in Secret Manager, mount into Cloud Run |
   | 11 | Deploy bg-generator Cloud Function + Cloud Scheduler job |

3. When done, the script prints your **Load Balancer IP**. Add a DNS A record:
   ```
   dashboard.your-domain.com  →  <LB IP>
   ```

4. Wait ~15 minutes for the managed SSL certificate to provision:
   ```bash
   gcloud compute ssl-certificates describe life-dashboard-cert --global
   ```

5. Open `https://dashboard.your-domain.com` — IAP prompts for your Google login.

---

## GitHub Actions

Deploys are triggered manually from the GitHub Actions UI — go to **Actions → Build & Deploy to Cloud Run → Run workflow**. `.github/workflows/deploy.yml`:
1. Builds and pushes the Docker image to Artifact Registry
2. Deploys the Cloud Run service
3. Deploys the **bg-generator Cloud Function** (so prompt/logic changes go live automatically)

### Setup (one-time, after running setup.sh)

`setup.sh` prints the values at the end. Add them to your GitHub repo under
**Settings → Secrets and variables → Actions → Variables**:

| Variable | Example value |
|---|---|
| `GCP_PROJECT_ID` | `my-dashboard-project` |
| `GCP_REGION` | `europe-west4` |
| `GCP_SERVICE_NAME` | `life-dashboard` |
| `GCP_IMAGE` | `europe-west4-docker.pkg.dev/…/app` |
| `GCP_WIF_PROVIDER` | `projects/…/providers/github-provider` |
| `GCP_SA_EMAIL` | `life-dashboard-sa@….iam.gserviceaccount.com` |

### Manual redeploy

```bash
docker build --platform linux/amd64 -t europe-west4-docker.pkg.dev/YOUR_PROJECT/life-dashboard/app:latest .
docker push europe-west4-docker.pkg.dev/YOUR_PROJECT/life-dashboard/app:latest
gcloud run deploy life-dashboard \
  --image=europe-west4-docker.pkg.dev/YOUR_PROJECT/life-dashboard/app:latest \
  --region=europe-west4
```

---

## Environment variables (Cloud Run)

| Variable | Source | Purpose |
|----------|--------|---------|
| `GCS_BUCKET` | set at deploy | TinyDB data bucket name |
| `SECRET_KEY` | Secret Manager | Flask session signing key |
| `API_KEY` | Secret Manager | API key for agents/scripts |
| `IAP_AUDIENCE` | set in Phase 8 | IAP JWT validation audience string |
| `GCAL_CALENDAR_ID` | set manually | Google Calendar ID to sync (default: `primary`) |
| `GCAL_SYNC_DAYS` | set manually | How many days ahead to fetch (default: `60`) |

---

## Google Calendar sync setup

One-time steps after initial deploy:

1. **Enable the Calendar API** on your GCP project:

   ```bash
   gcloud services enable calendar-json.googleapis.com \
     --project=YOUR_PROJECT_ID
   ```

2. **Find the Cloud Run service account email** — shown in the table above as `GCP_SA_EMAIL`, or look it up:

   ```bash
   gcloud run services describe life-dashboard \
     --region=europe-west4 --project=YOUR_PROJECT_ID \
     --format="get(spec.template.spec.serviceAccountName)"
   ```

3. **Share your Google Calendar** with that email — in Google Calendar (web), open the calendar's settings, scroll to *Share with specific people or groups*, add the SA email with **See all event details** permission.

4. **Set `GCAL_CALENDAR_ID`** to your Google account email (the owner of the calendar you shared):

   ```bash
   gcloud run services update life-dashboard \
     --region=europe-west4 \
     --project=YOUR_PROJECT_ID \
     --update-env-vars GCAL_CALENDAR_ID=your.email@gmail.com
   ```

5. Click **📅 GCal** in the dashboard to test. Check Cloud Run logs if it fails:

   ```bash
   gcloud logging read \
     "resource.type=cloud_run_revision AND resource.labels.service_name=life-dashboard" \
     --project=YOUR_PROJECT_ID --limit=20
   ```

---

## Generating a background image manually

The Cloud Function runs automatically at 06:00 Amsterdam time. To trigger it manually:

```bash
# Easiest — reads credentials from .env
./deploy/generate_bg.sh

# Via Cloud Scheduler (uses OIDC, same path as the daily run)
gcloud scheduler jobs run daily-bg-generate \
  --location=europe-west1 --project=YOUR_PROJECT_ID
```

See **[docs/BG_GENERATOR.md](BG_GENERATOR.md)** for full details including local prompt previewing.

---

## Data backup / restore

```bash
# Download
gcloud storage cp gs://YOUR_PROJECT-dashboard-data/dashboard.json ./data/dashboard.json

# Upload
gcloud storage cp ./data/dashboard.json gs://YOUR_PROJECT-dashboard-data/dashboard.json
```

---

## Tearing down

**Option A — GitHub Actions (recommended):**

Go to **Actions → Teardown GCP Infrastructure → Run workflow**, type `teardown` in the confirmation field. Removes Cloud Run, Cloud Function, Cloud Scheduler, Load Balancer, and Artifact Registry. GCS buckets, service account, and Workload Identity config are preserved so you can re-deploy later.

**Option B — local script:**

```bash
# Keeps your data in GCS
GCP_PROJECT_ID=your-project-id ./deploy/teardown.sh

# Deletes everything including data
GCP_PROJECT_ID=your-project-id ./deploy/teardown.sh --delete-data
```

> Note: DNS records are not touched by either method — remove them manually via your DNS provider if needed.

---

## Cost estimate (personal use)

| Resource | Free tier | Likely cost |
|---|---|---|
| Cloud Run | 2M req/month free | €0 |
| Cloud Function | 2M invocations free | €0 |
| Cloud Scheduler | 3 jobs free | €0 |
| GCS storage | 5 GB free | €0 |
| Gemini 2.5 Flash | per image | ~€0.01/day |
| Load Balancer | ~$18/month minimum | ~€17/month |
| Secret Manager | 10K access/month free | €0 |

> The Load Balancer is the main cost driver (~€17/month) — required for IAP on Cloud Run.
