#!/usr/bin/env bash
# =============================================================================
# Life Dashboard — GCP Teardown Script
# Removes all GCP resources created by setup.sh.
# Your data in GCS is preserved by default (see --delete-data flag below).
#
# Usage:
#   ./deploy/teardown.sh                  # keeps dashboard.json in GCS
#   ./deploy/teardown.sh --delete-data    # also deletes GCS bucket + data
# =============================================================================

set -euo pipefail

DELETE_DATA=false
if [[ "${1:-}" == "--delete-data" ]]; then
  DELETE_DATA=true
fi

# =============================================================================
# CONFIG — must match setup.sh
# =============================================================================

PROJECT_ID="${GCP_PROJECT_ID:?GCP_PROJECT_ID environment variable must be set}"
REGION="europe-west4"
SCHEDULER_LOCATION="europe-west1"   # Cloud Scheduler doesn't support europe-west4
SERVICE_NAME="life-dashboard"
BUCKET_NAME="${PROJECT_ID}-dashboard-data"
IMAGE_REPO="europe-west4-docker.pkg.dev/${PROJECT_ID}/life-dashboard"
SA_NAME="life-dashboard-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
SECRET_NAME="dashboard-secret-key"

# =============================================================================

echo ""
echo "▶ Tearing down Life Dashboard GCP resources..."
echo "  Project : ${PROJECT_ID}"
if [[ "${DELETE_DATA}" == "true" ]]; then
  echo "  WARNING : GCS data will also be deleted!"
fi
echo ""
read -rp "Continue? (yes/no): " CONFIRM
[[ "${CONFIRM}" == "yes" ]] || { echo "Aborted."; exit 0; }

gcloud config set project "${PROJECT_ID}"

# -- Load Balancer resources --------------------------------------------------
echo ""
echo "▶ Removing Load Balancer..."

gcloud compute forwarding-rules delete "${SERVICE_NAME}-https-rule" \
  --global --quiet --project="${PROJECT_ID}" 2>/dev/null || true

gcloud compute target-https-proxies delete "${SERVICE_NAME}-https-proxy" \
  --global --quiet --project="${PROJECT_ID}" 2>/dev/null || true

gcloud compute ssl-certificates delete "${SERVICE_NAME}-cert" \
  --global --quiet --project="${PROJECT_ID}" 2>/dev/null || true

gcloud compute url-maps delete "${SERVICE_NAME}-urlmap" \
  --global --quiet --project="${PROJECT_ID}" 2>/dev/null || true

gcloud compute backend-services delete "${SERVICE_NAME}-backend" \
  --global --quiet --project="${PROJECT_ID}" 2>/dev/null || true

gcloud compute network-endpoint-groups delete "${SERVICE_NAME}-neg" \
  --region="${REGION}" --quiet --project="${PROJECT_ID}" 2>/dev/null || true

gcloud compute addresses delete "${SERVICE_NAME}-ip" \
  --global --quiet --project="${PROJECT_ID}" 2>/dev/null || true

echo "✓ Load Balancer removed"

# -- Cloud Scheduler ----------------------------------------------------------
echo ""
echo "▶ Removing Cloud Scheduler job..."

gcloud scheduler jobs delete daily-bg-generate \
  --location="${SCHEDULER_LOCATION}" --quiet --project="${PROJECT_ID}" 2>/dev/null || true

echo "✓ Cloud Scheduler job removed"

# -- Cloud Function ------------------------------------------------------------
echo ""
echo "▶ Removing bg-generator Cloud Function..."

gcloud functions delete bg-generator \
  --gen2 --region="${REGION}" --quiet --project="${PROJECT_ID}" 2>/dev/null || true

echo "✓ Cloud Function removed"

# -- Cloud Run ----------------------------------------------------------------
echo ""
echo "▶ Removing Cloud Run service..."

gcloud run services delete "${SERVICE_NAME}" \
  --region="${REGION}" --quiet --project="${PROJECT_ID}" 2>/dev/null || true

echo "✓ Cloud Run service removed"

# -- Artifact Registry --------------------------------------------------------
echo ""
echo "▶ Removing container image..."

gcloud artifacts repositories delete "life-dashboard" \
  --location="europe-west4" --quiet --project="${PROJECT_ID}" 2>/dev/null || true

echo "✓ Container image removed"

# -- Secret Manager -----------------------------------------------------------
echo ""
echo "▶ Removing secret..."

gcloud secrets delete "${SECRET_NAME}" \
  --quiet --project="${PROJECT_ID}" 2>/dev/null || true

echo "✓ Secret removed"

# -- Service account ----------------------------------------------------------
echo ""
echo "▶ Removing service account..."

gcloud iam service-accounts delete "${SA_EMAIL}" \
  --quiet --project="${PROJECT_ID}" 2>/dev/null || true

echo "✓ Service account removed"

# -- GCS bucket (optional) ----------------------------------------------------
if [[ "${DELETE_DATA}" == "true" ]]; then
  echo ""
  echo "▶ Deleting GCS bucket and data..."
  gcloud storage rm -r "gs://${BUCKET_NAME}" --quiet 2>/dev/null || true
  echo "✓ Bucket deleted"
else
  echo ""
  echo "ℹ  GCS bucket gs://${BUCKET_NAME} preserved (your data is safe)."
  echo "   To also delete it, run:  ./deploy/teardown.sh --delete-data"
fi

# =============================================================================
echo ""
echo "✓ Teardown complete."
echo ""
echo "  Remember to remove the DNS A record for your domain."
