"""Flask application factory."""
from flask import Flask
from .database import init_db


def create_app() -> Flask:
    app = Flask(__name__)
    import os, secrets
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

    # API key for agent/script access to /api/* routes.
    # Generated at deploy time and injected via Secret Manager → Cloud Run env var.
    # When absent (local dev), all /api/* requests are allowed.
    app.config["API_KEY"] = os.environ.get("API_KEY") or None

    # Limit request body size to 1 MB to prevent trivial DoS via large payloads.
    app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024

    # Initialise NoSQL database and seed if empty
    init_db()

    # Register blueprints
    from .routes import main as main_bp
    app.register_blueprint(main_bp)

    # ── Security response headers ─────────────────────────────────────────────
    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # 'unsafe-inline' for script-src is required by the current inline
        # onclick handlers in index.html.  Migrate to external listeners to
        # allow tightening this directive in the future.
        response.headers.setdefault(
            "Content-Security-Policy",
            (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' https://storage.googleapis.com data:; "
                "connect-src 'self' https://storage.googleapis.com; "
                "font-src 'self'; "
                "frame-ancestors 'none';"
            ),
        )
        return response

    return app
