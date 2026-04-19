#!/usr/bin/env bash
# Manually trigger background image generation.
# Usage: ./deploy/generate_bg.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env"

# Load .env
if [[ -f "${ENV_FILE}" ]]; then
  set -o allexport
  source "${ENV_FILE}"
  set +o allexport
fi

FUNCTION_URL="${FUNCTION_URL:-https://bg-generator-xxxx-ez.a.run.app}"

if [[ -z "${API_KEY:-}" ]]; then
  echo "ERROR: API_KEY not set in .env"
  exit 1
fi

echo "Triggering background image generation..."
ID_TOKEN=$(gcloud auth print-identity-token 2>/dev/null || true)

if [[ -z "${ID_TOKEN}" ]]; then
  echo "ERROR: Could not get identity token. Run: gcloud auth login"
  exit 1
fi

response=$(curl -s -X POST "${FUNCTION_URL}" \
  -H "Authorization: Bearer ${ID_TOKEN}" \
  -H "X-Api-Key: ${API_KEY}")
echo "${response}" | python3 -m json.tool 2>/dev/null || echo "${response}"
