"""Sleeve & Shelf: application factory."""

import argparse
import os
from pathlib import Path

from flask import Flask, abort, redirect, request, url_for
from flask_babel import Babel

from sleeve_shelf.collection import replace_collection
from sleeve_shelf.ingestion.initial_load import load_initial_layout
from sleeve_shelf.persistence import JsonStore

from sleeve_shelf.web import browse, setup
from sleeve_shelf.web.context import has_collection

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def create_app(data_dir: str | Path | None = None) -> Flask:
    """Create and configure the Flask application instance."""
    app = Flask(__name__, template_folder="web/templates", static_folder="web/static")
    app.config["DATA_DIR"] = _data_dir(data_dir)
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


def _data_dir(data_dir: str | Path | None = None) -> Path:
    return Path(data_dir or os.environ.get("SLEEVE_SHELF_DATA_DIR", "data")).resolve()


def main(arguments: list[str] | None = None) -> None:
    """Run the app with Flask's built-in server, or load a workbook from the command line."""
    parser = argparse.ArgumentParser(prog="sleeve-shelf")
    commands = parser.add_subparsers(dest="command")
    load = commands.add_parser(
        "load", help="load a layout workbook, replacing the stored collection"
    )
    load.add_argument("workbook", type=Path)
    options = parser.parse_args(arguments)

    if options.command == "load":
        # Same effect as the upload in the wizard, for when a browser can't upload.
        result = load_initial_layout(options.workbook)
        replace_collection(JsonStore(_data_dir()), result)
        print(
            f"Loaded {len(result.albums)} albums on {len(result.shelves)} shelves"
            f" into {_data_dir()}"
        )
        return

    create_app().run(
        host=os.environ.get("SLEEVE_SHELF_HOST", "127.0.0.1"),
        port=int(os.environ.get("SLEEVE_SHELF_PORT", "5000")),
    )
