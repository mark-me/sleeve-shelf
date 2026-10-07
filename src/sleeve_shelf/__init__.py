"""Sleeve & Shelf: application factory."""

import os
from pathlib import Path

from flask import Flask, abort, redirect, request, url_for
from flask_babel import Babel

from sleeve_shelf.web import browse, setup
from sleeve_shelf.web.context import has_collection

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def create_app(data_dir: str | Path | None = None) -> Flask:
    """Create and configure the Flask application instance."""
    app = Flask(__name__, template_folder="web/templates", static_folder="web/static")
    app.config["DATA_DIR"] = Path(
        data_dir or os.environ.get("SLEEVE_SHELF_DATA_DIR", "data")
    ).resolve()
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    Babel(app, default_locale="en")

    app.register_blueprint(setup.blueprint)
    app.register_blueprint(browse.blueprint)

    @app.before_request
    def reject_cross_site_posts():
        # Browsers label where a request comes from; another site must not be
        # able to replace the collection by posting a form to this app.
        if request.method == "POST" and request.headers.get("Sec-Fetch-Site") == "cross-site":
            abort(403)

    @app.get("/")
    def index():
        return redirect(url_for("browse.browse" if has_collection() else "setup.welcome"))

    return app


def main() -> None:
    """Run the app with Flask's built-in server."""
    create_app().run(
        host=os.environ.get("SLEEVE_SHELF_HOST", "127.0.0.1"),
        port=int(os.environ.get("SLEEVE_SHELF_PORT", "5000")),
    )
