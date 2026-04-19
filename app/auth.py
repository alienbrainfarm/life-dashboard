"""
API authentication helpers.

Valid auth paths for /api/* and /mcp routes:

  1. IAP (browser)
     Requests arriving via the Global Load Balancer + IAP carry the signed
     X-Goog-IAP-JWT-Assertion header.  We validate that JWT's signature
     against Google's public keys to prove Google IAP issued it.
     The plain X-Goog-Authenticated-User-Email header is NOT trusted on its
     own because the Cloud Run URL is publicly reachable and anyone can forge
     that header.  IAP_AUDIENCE must be set to the backend-service resource
     string: /projects/<project_number>/global/backendServices/<service_id>

  2. API key (agents / scripts)
     Callers that hit the Cloud Run URL directly (bypassing the LB/IAP) must
     supply a matching secret in the X-Api-Key header.
     The key is generated at deploy time, stored in Secret Manager, and
     injected into the container as the API_KEY environment variable.

  3. Google OAuth Bearer token (Cowork / MCP connector flow)
     When Cowork authenticates via Google OAuth and connects to the /mcp
     endpoint it sends an Authorization: Bearer <token> header.  We validate
     the token against Google's tokeninfo endpoint and check it belongs to
     the expected account.

  4. Local dev (no key configured)
     When API_KEY is not set in the environment, all requests are allowed.
     This makes local Docker development frictionless.
"""

import logging
import os

import requests as http_requests
from flask import current_app, request

logger = logging.getLogger(__name__)

ALLOWED_EMAIL = os.environ.get("ALLOWED_EMAIL", "")
# Audience for IAP JWT validation:
# /projects/<project_number>/global/backendServices/<backend_service_id>
IAP_AUDIENCE = os.environ.get("IAP_AUDIENCE", "")


def _verify_iap_jwt(iap_jwt: str) -> bool:
    """Validate the signed IAP JWT using Google's public keys.

    Returns True only when the JWT is cryptographically valid and the
    audience matches IAP_AUDIENCE.  Returns False on any error so the
    caller falls through to other auth paths.
    """
    if not IAP_AUDIENCE:
        logger.warning(
            "IAP_AUDIENCE env var is not set; IAP JWT validation is disabled. "
            "Set IAP_AUDIENCE to /projects/<num>/global/backendServices/<id>."
        )
        return False
    try:
        from google.auth.transport import requests as google_requests
        import google.oauth2.id_token

        google_req = google_requests.Request()
        google.oauth2.id_token.verify_token(
            iap_jwt,
            google_req,
            audience=IAP_AUDIENCE,
            certs_url="https://www.gstatic.com/iap/verify/public_key",
        )
        return True
    except Exception as exc:
        logger.debug("IAP JWT validation failed: %s", exc)
        return False


def _validate_google_bearer(token: str) -> bool:
    """Validate a Google OAuth/OIDC Bearer token via Google's tokeninfo endpoint."""
    if not ALLOWED_EMAIL:
        return False
    try:
        resp = http_requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": token},
            timeout=3,
        )
        if resp.status_code == 200:
            info = resp.json()
            email = info.get("email", "")
            return email == ALLOWED_EMAIL
        # Try access_token path as fallback
        resp2 = http_requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"access_token": token},
            timeout=3,
        )
        if resp2.status_code == 200:
            info2 = resp2.json()
            email2 = info2.get("email", "")
            return email2 == ALLOWED_EMAIL
    except Exception:
        pass
    return False


def api_authorized() -> bool:
    """Return True if the current request is authorised to use the API."""

    # ── Path 1: IAP browser session ───────────────────────────────────────────
    # Validate the cryptographically signed IAP JWT — do NOT trust the plain
    # X-Goog-Authenticated-User-Email header alone, as it can be forged by
    # callers who reach the Cloud Run URL directly.
    iap_jwt = request.headers.get("X-Goog-IAP-JWT-Assertion", "")
    if iap_jwt and _verify_iap_jwt(iap_jwt):
        return True

    # ── Path 2: API key ───────────────────────────────────────────────────────
    api_key = current_app.config.get("API_KEY")
    if api_key and request.headers.get("X-Api-Key") == api_key:
        return True

    # ── Path 3: Google OAuth Bearer token (Cowork connector) ─────────────────
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
        if _validate_google_bearer(token):
            return True

    # ── Path 4: Local dev (no key configured) ─────────────────────────────────
    if not api_key:
        return True

    return False
