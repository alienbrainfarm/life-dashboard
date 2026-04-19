"""Entry point for the Life Dashboard application."""
import os

# In local dev the .env file contains API_KEY for scripts/curl usage, but the
# browser has no way to send it.  When running the dev server directly we clear
# it so auth path-4 ("no key configured → allow all") kicks in.
if os.environ.get("FLASK_ENV") != "production" and not os.environ.get("GCS_BUCKET"):
    os.environ.pop("API_KEY", None)

from app import create_app

app = create_app()

if __name__ == "__main__":
    print("\n🗓  Life Dashboard is running → http://127.0.0.1:5000\n")
    app.run(debug=True, port=5000)
