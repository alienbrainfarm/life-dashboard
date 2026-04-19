#!/usr/bin/env bash
# =============================================================================
# Life Dashboard — GCP Setup Script
# Deploys the app to Cloud Run with GCS data storage and IAP protection.
#
# Prerequisites:
#   - gcloud CLI installed and authenticated  (gcloud auth login)
#   - Docker installed and running
#   - A GCP project created and set as default
#   - A domain name you control (for the Load Balancer SSL cert + IAP)
#   - OAuth consent screen configured in the GCP Console (see DEPLOY.md)
#
# Usage:
#   1. Copy .env.example to .env in the project root and fill in values
#   2. chmod +x deploy/setup.sh
#   3. ./deploy/setup.sh
# =============================================================================

set -euo pipefail

# =============================================================================
# CONFIG — loaded from .env in the project root
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Error: .env file not found at ${ENV_FILE}"
  echo "Copy .env.example to .env and fill in your values."
  exit 1
fi

# shellcheck source=../.env
set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

: "${PROJECT_ID:?PROJECT_ID must be set in .env}"
: "${REGION:?REGION must be set in .env}"
: "${DOMAIN:?DOMAIN must be set in .env}"
: "${IAP_USER:?IAP_USER must be set in .env}"
: "${GITHUB_REPO:?GITHUB_REPO must be set in .env}"

# -- Derived names (no need to change) ----------------------------------------
SERVICE_NAME="life-dashboard"
BUCKET_NAME="${PROJECT_ID}-dashboard-data"
BG_BUCKET_NAME="${PROJECT_ID}-dashboard-bg"   # separate public bucket for AI background images
IMAGE="europe-west4-docker.pkg.dev/${PROJECT_ID}/life-dashboard/app"
SA_NAME="life-dashboard-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
SECRET_NAME="dashboard-secret-key"
API_SECRET_NAME="dashboard-api-key"

# =============================================================================
# PHASE 1 — Enable APIs
# =============================================================================
echo ""
echo "▶ Phase 1: Enabling GCP APIs..."

gcloud config set project "${PROJECT_ID}"

gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  cloudfunctions.googleapis.com \
  storage.googleapis.com \
  iap.googleapis.com \
  compute.googleapis.com \
  secretmanager.googleapis.com \
  aiplatform.googleapis.com \
  cloudscheduler.googleapis.com \
  --project="${PROJECT_ID}"

echo "✓ APIs enabled"

# =============================================================================
# PHASE 2 — Service account
# =============================================================================
echo ""
echo "▶ Phase 2: Creating service account..."

gcloud iam service-accounts create "${SA_NAME}" \
  --display-name="Life Dashboard Service Account" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  (already exists, continuing)"

# Grant Cloud Run deploy + IAM permissions (needed for GitHub Actions and Cloud Functions Gen2)
# run.admin is required over run.developer because Cloud Functions Gen2 sets IAM policy
# on the backing Cloud Run service when deploying with --no-allow-unauthenticated
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.admin"

# Grant Cloud Functions deploy permissions (needed for GitHub Actions bg-generator deploy)
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/cloudfunctions.developer"

# Allow the SA to act as itself when deploying Cloud Run revisions
gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/iam.serviceAccountUser" \
  --project="${PROJECT_ID}"

# Allow the SA to act as the default compute SA (required by Cloud Functions Gen2 builds)
_PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="get(projectNumber)")
gcloud iam service-accounts add-iam-policy-binding "${_PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/iam.serviceAccountUser" \
  --project="${PROJECT_ID}"

# Grant Vertex AI Imagen access (used by the daily background image generator)
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/aiplatform.user"

echo "✓ Service account: ${SA_EMAIL}"

# =============================================================================
# PHASE 3 — GCS bucket + upload initial data
# =============================================================================
echo ""
echo "▶ Phase 3: Creating GCS bucket and uploading data..."

gcloud storage buckets create "gs://${BUCKET_NAME}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --uniform-bucket-level-access 2>/dev/null || echo "  (bucket already exists, continuing)"

# Grant the service account access to the bucket
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectAdmin"

# Upload the current dashboard data
DATA_FILE="${SCRIPT_DIR}/../data/dashboard.json"

if [[ -f "${DATA_FILE}" ]]; then
  gcloud storage cp "${DATA_FILE}" "gs://${BUCKET_NAME}/dashboard.json"
  echo "✓ Uploaded dashboard.json to gs://${BUCKET_NAME}"
else
  echo "  (no local dashboard.json found — GCS object will be created on first write)"
fi

# =============================================================================
# PHASE 4 — Secret Manager (Flask SECRET_KEY)
# =============================================================================
echo ""
echo "▶ Phase 4: Creating Flask SECRET_KEY in Secret Manager..."

python3 -c "import secrets; print(secrets.token_hex(32))" | \
  gcloud secrets create "${SECRET_NAME}" \
    --data-file=- \
    --project="${PROJECT_ID}" 2>/dev/null || echo "  (secret already exists, skipping)"

gcloud secrets add-iam-policy-binding "${SECRET_NAME}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" \
  --project="${PROJECT_ID}"

echo "✓ Secret created"

# =============================================================================
# PHASE 5 — Build and push container image
# =============================================================================
echo ""
echo "▶ Phase 5: Building and pushing container image..."

# Create Artifact Registry repository
gcloud artifacts repositories create life-dashboard \
  --repository-format=docker \
  --location="europe-west4" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  (repository already exists, continuing)"

# Grant service account permission to push images (needed for GitHub Actions)
gcloud artifacts repositories add-iam-policy-binding life-dashboard \
  --location="europe-west4" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/artifactregistry.writer" \
  --project="${PROJECT_ID}"

# Configure Docker auth
gcloud auth configure-docker "europe-west4-docker.pkg.dev" --quiet

# Build and push (from project root)
cd "${SCRIPT_DIR}/.."
docker build --platform linux/amd64 -t "${IMAGE}:latest" .
docker push "${IMAGE}:latest"

echo "✓ Image pushed: ${IMAGE}:latest"

# =============================================================================
# PHASE 6 — Deploy to Cloud Run (no public access — IAP controls access)
# =============================================================================
echo ""
echo "▶ Phase 6: Deploying to Cloud Run..."

gcloud run deploy "${SERVICE_NAME}" \
  --image="${IMAGE}:latest" \
  --region="${REGION}" \
  --platform=managed \
  --service-account="${SA_EMAIL}" \
  --set-env-vars="GCS_BUCKET=${BUCKET_NAME}" \
  --update-secrets="SECRET_KEY=${SECRET_NAME}:latest" \
  --no-allow-unauthenticated \
  --min-instances=0 \
  --max-instances=2 \
  --memory=256Mi \
  --cpu=1 \
  --timeout=60 \
  --project="${PROJECT_ID}"

echo "✓ Cloud Run service deployed"

# =============================================================================
# PHASE 7 — Load Balancer + IAP
# =============================================================================
echo ""
echo "▶ Phase 7: Setting up Load Balancer and IAP..."

# Reserve a static external IP
gcloud compute addresses create "${SERVICE_NAME}-ip" \
  --global \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  (IP already exists, continuing)"

LB_IP=$(gcloud compute addresses describe "${SERVICE_NAME}-ip" \
  --global \
  --format="get(address)" \
  --project="${PROJECT_ID}")
echo "  Load Balancer IP: ${LB_IP}"

# Serverless NEG pointing to the Cloud Run service
gcloud compute network-endpoint-groups create "${SERVICE_NAME}-neg" \
  --region="${REGION}" \
  --network-endpoint-type=serverless \
  --cloud-run-service="${SERVICE_NAME}" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  (NEG already exists, continuing)"

# Backend service
gcloud compute backend-services create "${SERVICE_NAME}-backend" \
  --global \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  (backend service already exists, continuing)"

gcloud compute backend-services add-backend "${SERVICE_NAME}-backend" \
  --global \
  --network-endpoint-group="${SERVICE_NAME}-neg" \
  --network-endpoint-group-region="${REGION}" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  (backend already added, continuing)"

# Enable IAP on the backend service
gcloud compute backend-services update "${SERVICE_NAME}-backend" \
  --global \
  --iap=enabled \
  --project="${PROJECT_ID}"

# URL map, HTTPS proxy, forwarding rule
gcloud compute url-maps create "${SERVICE_NAME}-urlmap" \
  --default-service="${SERVICE_NAME}-backend" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  (URL map already exists, continuing)"

# Managed SSL certificate for the domain
gcloud compute ssl-certificates create "${SERVICE_NAME}-cert" \
  --domains="${DOMAIN}" \
  --global \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  (SSL cert already exists, continuing)"

gcloud compute target-https-proxies create "${SERVICE_NAME}-https-proxy" \
  --url-map="${SERVICE_NAME}-urlmap" \
  --ssl-certificates="${SERVICE_NAME}-cert" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  (HTTPS proxy already exists, continuing)"

gcloud compute forwarding-rules create "${SERVICE_NAME}-https-rule" \
  --global \
  --target-https-proxy="${SERVICE_NAME}-https-proxy" \
  --address="${SERVICE_NAME}-ip" \
  --ports=443 \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  (forwarding rule already exists, continuing)"

echo "✓ Load Balancer configured"

# =============================================================================
# PHASE 8 — Grant IAP access to your Google account + Cloud Run invoker
# =============================================================================
echo ""
echo "▶ Phase 8: Granting IAP access to ${IAP_USER}..."

# Provision the IAP service account (must exist before granting roles)
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="get(projectNumber)")
gcloud beta services identity create \
  --service=iap.googleapis.com \
  --project="${PROJECT_ID}"

# The IAP service account needs to be able to invoke the Cloud Run service
gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
  --region="${REGION}" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com" \
  --role="roles/run.invoker" \
  --project="${PROJECT_ID}"

echo "✓ IAP service account granted Cloud Run invoker role"

# Get the backend service number for IAP IAM binding
BACKEND_ID=$(gcloud compute backend-services describe "${SERVICE_NAME}-backend" \
  --global \
  --format="get(id)" \
  --project="${PROJECT_ID}")

gcloud iap web add-iam-policy-binding \
  --resource-type=backend-services \
  --service="${SERVICE_NAME}-backend" \
  --member="user:${IAP_USER}" \
  --role="roles/iap.httpsResourceAccessor" \
  --project="${PROJECT_ID}"

echo "✓ IAP access granted to ${IAP_USER}"

# Inject the IAP audience into Cloud Run so the app can validate IAP JWTs.
# The audience is: /projects/<project_number>/global/backendServices/<backend_id>
IAP_AUDIENCE="/projects/${PROJECT_NUMBER}/global/backendServices/${BACKEND_ID}"
gcloud run services update "${SERVICE_NAME}" \
  --region="${REGION}" \
  --update-env-vars="IAP_AUDIENCE=${IAP_AUDIENCE}" \
  --project="${PROJECT_ID}"

echo "✓ IAP_AUDIENCE set to ${IAP_AUDIENCE}"

# =============================================================================
# PHASE 9 — Workload Identity Federation (keyless GitHub Actions auth)
# =============================================================================
echo ""
echo "▶ Phase 9: Configuring Workload Identity Federation for GitHub Actions..."

WIF_POOL="github-pool"
WIF_PROVIDER="github-provider"

# Create the Workload Identity Pool
gcloud iam workload-identity-pools create "${WIF_POOL}" \
  --location=global \
  --display-name="GitHub Actions Pool" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  (pool already exists, continuing)"

# Create the OIDC provider for GitHub
gcloud iam workload-identity-pools providers create-oidc "${WIF_PROVIDER}" \
  --location=global \
  --workload-identity-pool="${WIF_POOL}" \
  --display-name="GitHub OIDC Provider" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.actor=assertion.actor" \
  --attribute-condition="assertion.repository=='${GITHUB_REPO}'" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  (provider already exists, continuing)"

# Get the full pool resource name
WIF_POOL_NAME=$(gcloud iam workload-identity-pools describe "${WIF_POOL}" \
  --location=global \
  --format="get(name)" \
  --project="${PROJECT_ID}")

# Allow GitHub Actions (from your repo) to impersonate the service account
gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${WIF_POOL_NAME}/attribute.repository/${GITHUB_REPO}" \
  --project="${PROJECT_ID}"

# Print the values needed for the GitHub Actions workflow
WIF_PROVIDER_NAME=$(gcloud iam workload-identity-pools providers describe "${WIF_PROVIDER}" \
  --location=global \
  --workload-identity-pool="${WIF_POOL}" \
  --format="get(name)" \
  --project="${PROJECT_ID}")

echo "✓ Workload Identity Federation configured"

# =============================================================================
# PHASE 10 — API key (agent / script access)
# =============================================================================
echo ""
echo "▶ Phase 10: Generating API key for agent/script access..."

# Generate a 32-byte hex key and store it in Secret Manager
API_KEY_VALUE=$(openssl rand -hex 32)

gcloud secrets create "${API_SECRET_NAME}" \
  --replication-policy=automatic \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  (secret already exists, rotating version)"

echo -n "${API_KEY_VALUE}" | \
  gcloud secrets versions add "${API_SECRET_NAME}" \
    --data-file=- \
    --project="${PROJECT_ID}"

# Grant the Cloud Run service account read access
gcloud secrets add-iam-policy-binding "${API_SECRET_NAME}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" \
  --project="${PROJECT_ID}"

# Mount the secret into the running Cloud Run service as API_KEY env var
gcloud run services update "${SERVICE_NAME}" \
  --region="${REGION}" \
  --update-secrets="API_KEY=${API_SECRET_NAME}:latest" \
  --project="${PROJECT_ID}"

# Allow unauthenticated access to the Cloud Run URL so agents can call the API
# directly (bypassing the LB/IAP layer).  Flask enforces the X-Api-Key check.
gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
  --region="${REGION}" \
  --member="allUsers" \
  --role="roles/run.invoker" \
  --project="${PROJECT_ID}"

# Retrieve the direct Cloud Run URL for agents
CLOUDRUN_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --format="get(status.url)" \
  --project="${PROJECT_ID}")

echo "✓ API key created and mounted"

# =============================================================================
# PHASE 11 — AI Background Generator (Cloud Function + Cloud Scheduler)
# =============================================================================
echo ""
echo "▶ Phase 11: Setting up AI background image generator (Cloud Function)..."

# Create a separate public GCS bucket for AI-generated background images.
# This is intentionally public (read-only) — images are AI-generated landscapes
# with no personal data.  The main data bucket (dashboard.json) stays private.
gcloud storage buckets create "gs://${BG_BUCKET_NAME}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --uniform-bucket-level-access 2>/dev/null || echo "  (bg bucket already exists, continuing)"

# Allow the dashboard domain to make cross-origin HEAD/GET requests for the
# background image.  Without this browsers block the fetch() call silently.
gsutil cors set - "gs://${BG_BUCKET_NAME}" << CORS_EOF
[{"origin":["https://${DOMAIN}"],"method":["HEAD","GET"],"responseHeader":["Content-Type"],"maxAgeSeconds":3600}]
CORS_EOF

# Grant public read access to all objects in the bg bucket
gcloud storage buckets add-iam-policy-binding "gs://${BG_BUCKET_NAME}" \
  --member="allUsers" \
  --role="roles/storage.objectViewer"

# Grant the service account write access to the bg bucket
gcloud storage buckets add-iam-policy-binding "gs://${BG_BUCKET_NAME}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectAdmin"

# Deploy the Cloud Function (gen2) from functions/bg_generator/
# Authentication is handled by Cloud IAM (no --allow-unauthenticated).
# Cloud Scheduler authenticates via OIDC so no API key is needed at the
# transport layer; the function still enforces its own API_KEY check as
# defense-in-depth.
gcloud functions deploy bg-generator \
  --gen2 \
  --runtime=python312 \
  --region="${REGION}" \
  --source=functions/bg_generator \
  --entry-point=generate_background \
  --trigger-http \
  --no-allow-unauthenticated \
  --service-account="${SA_EMAIL}" \
  --set-env-vars="GCS_BUCKET=${BUCKET_NAME},BG_BUCKET=${BG_BUCKET_NAME},GCP_PROJECT=${PROJECT_ID}" \
  --update-secrets="API_KEY=${API_SECRET_NAME}:latest" \
  --memory=512Mi \
  --timeout=300s \
  --project="${PROJECT_ID}"

FUNCTION_URL=$(gcloud functions describe bg-generator \
  --region="${REGION}" \
  --format="get(serviceConfig.uri)" \
  --project="${PROJECT_ID}")

# Grant the app service account permission to invoke the bg-generator function.
# Cloud Scheduler will request an OIDC token for SA_EMAIL and attach it to the
# HTTP request.  Gen2 functions run on Cloud Run — grant roles/run.invoker there.
gcloud run services add-iam-policy-binding bg-generator \
  --region="${REGION}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker" \
  --project="${PROJECT_ID}"

echo "✓ ${SA_EMAIL} granted Cloud Run invoker role on bg-generator"

# Cloud Scheduler does not support europe-west4; use europe-west1 (Belgium).
# The job still targets the function in europe-west4 — cross-region is fine.
SCHEDULER_LOCATION="europe-west1"

# Create/update Cloud Scheduler job — authenticates via OIDC (no API key header)
gcloud scheduler jobs create http daily-bg-generate \
  --location="${SCHEDULER_LOCATION}" \
  --schedule="0 6 * * *" \
  --time-zone="Europe/Amsterdam" \
  --uri="${FUNCTION_URL}" \
  --http-method=POST \
  --oidc-service-account-email="${SA_EMAIL}" \
  --oidc-token-audience="${FUNCTION_URL}" \
  --attempt-deadline=300s \
  --project="${PROJECT_ID}" 2>/dev/null || \
gcloud scheduler jobs update http daily-bg-generate \
  --location="${SCHEDULER_LOCATION}" \
  --schedule="0 6 * * *" \
  --time-zone="Europe/Amsterdam" \
  --uri="${FUNCTION_URL}" \
  --http-method=POST \
  --oidc-service-account-email="${SA_EMAIL}" \
  --oidc-token-audience="${FUNCTION_URL}" \
  --attempt-deadline=300s \
  --project="${PROJECT_ID}"

echo "✓ AI background generator configured"
echo "  Cloud Function           : bg-generator (${FUNCTION_URL})"
echo "  Background images bucket : gs://${BG_BUCKET_NAME} (public read)"
echo "  Cloud Scheduler job      : daily-bg-generate (06:00 Europe/Amsterdam)"

# =============================================================================
# DONE
# =============================================================================
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Setup complete!                                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "  Load Balancer IP : ${LB_IP}"
echo "  Dashboard URL    : https://${DOMAIN}  (browser, IAP protected)"
echo "  API base URL     : ${CLOUDRUN_URL}/api  (agents, API key protected)"
echo "  IAP audience     : ${IAP_AUDIENCE}"
echo "  BG images bucket : gs://${BG_BUCKET_NAME}  (public read, AI landscapes only)"
echo "  Scheduler job    : daily-bg-generate  (06:00 Europe/Amsterdam, OIDC auth)"
echo ""
echo "  API key is stored in Secret Manager only — retrieve it with:"
echo "  gcloud secrets versions access latest --secret=${API_SECRET_NAME} --project=${PROJECT_ID}"
echo ""
echo "GitHub Actions — add these as repository variables"
echo "  (Settings → Secrets and variables → Actions → Variables):"
echo ""
echo "  GCP_PROJECT_ID          = ${PROJECT_ID}"
echo "  GCP_REGION              = ${REGION}"
echo "  GCP_SERVICE_NAME        = ${SERVICE_NAME}"
echo "  GCP_IMAGE               = ${IMAGE}"
echo "  GCP_WIF_PROVIDER        = ${WIF_PROVIDER_NAME}"
echo "  GCP_SA_EMAIL            = ${SA_EMAIL}"
echo ""
echo "Next steps:"
echo "  1. Add the variables above to your GitHub repo"
echo "  2. Point your DNS A record for ${DOMAIN} → ${LB_IP}"
echo "  3. Wait ~15 min for the managed SSL certificate to provision"
echo "  4. Trigger a deploy manually from the GitHub Actions UI (workflow_dispatch)"
echo "  5. Open https://${DOMAIN} — IAP will prompt for your Google login"
echo "  6. (Optional) Trigger the bg generator manually to test:"
echo "     gcloud scheduler jobs run daily-bg-generate --location=${REGION} --project=${PROJECT_ID}"
echo ""
echo "Note: If you haven't yet set up the OAuth consent screen,"
echo "      see docs/DEPLOY.md — this is a one-time manual step in the Console."
