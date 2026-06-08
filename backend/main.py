"""Flask entry point for Gas-off backend."""

import logging
import os

from flask import Flask, send_from_directory, request

from backend.config.settings import settings
from backend.handlers.bot_handler import bp as bot_bp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder=None)

# Manual CORS
@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin", "")
    if origin in settings.ALLOWED_ORIGINS or "localhost" in origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

# Handle OPTIONS preflight
@app.before_request
def handle_options():
    if request.method == "OPTIONS":
        return "", 204

# Register blueprints
app.register_blueprint(bot_bp)

# Serve TWA static files
TWA_BUILD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "frontend", "build", "web"
)


@app.route("/twa/")
@app.route("/twa/<path:_>")
def serve_twa(_=None):
    """Serve the TWA SPA for any /twa/* path."""
    return send_from_directory(TWA_BUILD_DIR, "index.html")


@app.route("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


if __name__ == "__main__":
    logger.info(f"Starting Gas-off backend on {settings.HOST}:{settings.PORT}")
    app.run(host=settings.HOST, port=settings.PORT, debug=True)
