"""Sleeve & Shelf: application factory."""

import argparse
import os
from pathlib import Path

from flask import Flask, abort, redirect, request, url_for
from flask_babel import Babel

from sleeve_shelf.collection import (
    enrich_collection,
    import_discogs_collection,
    load_layout,
)
from sleeve_shelf.config import load_settings
from sleeve_shelf.ingestion.discogs_api import DiscogsClient, DiscogsError
from sleeve_shelf.ingestion.discogs_csv import read_collection
from sleeve_shelf.ingestion.initial_load import load_initial_layout
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.web import (
    albums,
    artists,
    browse,
    clusters,
    dashboard,
    discogs,
    families,
    layout,
    pwa,
    rules,
    settings,
    setup,
    storage,
    versions,
)
from sleeve_shelf.web import proposal as proposal_screen
from sleeve_shelf.web.context import get_store, has_collection
from sleeve_shelf.web.waiting import menu_counts

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def create_app(data_dir: str | Path | None = None) -> Flask:
    """Create and configure the Flask application instance."""
    app = Flask(__name__, template_folder="web/templates", static_folder="web/static")
    app.config["DATA_DIR"] = _data_dir(data_dir)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    # Set by the Docker image build; a local run has no version.
    app.config["VERSION"] = os.environ.get("SLEEVE_SHELF_VERSION", "dev")
    Babel(app, default_locale="en")

    app.register_blueprint(setup.blueprint)
    app.register_blueprint(browse.blueprint)
    app.register_blueprint(storage.blueprint)
    app.register_blueprint(discogs.blueprint)
    app.register_blueprint(families.blueprint)
    app.register_blueprint(proposal_screen.blueprint)
    app.register_blueprint(artists.blueprint)
    app.register_blueprint(settings.blueprint)
    app.register_blueprint(rules.blueprint)
    app.register_blueprint(layout.blueprint)
    app.register_blueprint(clusters.blueprint)
    app.register_blueprint(versions.blueprint)
    app.register_blueprint(dashboard.blueprint)
    app.register_blueprint(albums.blueprint)
    app.register_blueprint(pwa.blueprint)

    @app.before_request
    def reject_cross_site_posts():
        # Browsers label where a request comes from; another site must not be
        # able to replace the collection by posting a form to this app.
        if request.method == "POST" and request.headers.get("Sec-Fetch-Site") == "cross-site":
            abort(403)

    @app.context_processor
    def menu():
        # The numbers behind menu items: where something is waiting for the user.
        return {"menu_counts": menu_counts(get_store()) if has_collection() else {}}

    @app.get("/")
    def index():
        return redirect(url_for("dashboard.index" if has_collection() else "setup.welcome"))

    return app


def _data_dir(data_dir: str | Path | None = None) -> Path:
    return Path(data_dir or os.environ.get("SLEEVE_SHELF_DATA_DIR", "data")).resolve()


def main(arguments: list[str] | None = None) -> None:
    """Run the app with Flask's built-in server, or load a workbook from the command line."""
    parser = argparse.ArgumentParser(prog="sleeve-shelf")
    commands = parser.add_subparsers(dest="command")
    load = commands.add_parser(
        "load", help="load a layout workbook; once a collection exists only the layout changes"
    )
    load.add_argument("workbook", type=Path)
    import_discogs = commands.add_parser(
        "import-discogs", help="link the collection to a Discogs CSV export"
    )
    import_discogs.add_argument("export", type=Path)
    commands.add_parser("enrich", help="fetch styles and original years from Discogs")
    options = parser.parse_args(arguments)

    data_dir = _data_dir()
    settings = load_settings(data_dir)
    store = JsonStore(data_dir)

    if options.command == "load":
        # Same effect as the upload in the wizard, for when a browser can't upload.
        result = load_initial_layout(options.workbook, settings.base_width_cm)
        load_layout(store, result, settings.width_constants)
        print(
            f"Loaded {len(result.albums)} albums on {len(result.shelves)} shelves"
            f" into {data_dir}"
        )
        return

    if options.command == "import-discogs":
        items = read_collection(options.export, settings.count_bonus_discs_as_vinyl)
        outcome = import_discogs_collection(store, items, settings.width_constants)
        print(
            f"{outcome.vinyl_count} vinyl releases ({outcome.skipped_non_vinyl} other skipped):"
            f" {outcome.matched} linked to loaded albums, {outcome.proposed} proposed for"
            f" confirmation, {outcome.added} added as new albums;"
            f" {outcome.unmatched_albums} loaded albums have no release."
        )
        return

    if options.command == "enrich":
        if not settings.discogs_token:
            parser.exit(1, f"No Discogs token in {data_dir / 'config.yaml'}\n")

        def show(done: int, total: int) -> None:
            if done % 20 < 2 or done >= total:
                print(f"{done} of about {total} lookups", flush=True)

        try:
            lookups = enrich_collection(store, DiscogsClient(settings.discogs_token), show)
        except DiscogsError as error:
            parser.exit(1, f"Stopped: {error} Run it again to continue.\n")
        print(f"Enrichment complete after {lookups} lookups.")
        return

    create_app().run(
        host=os.environ.get("SLEEVE_SHELF_HOST", "127.0.0.1"),
        port=int(os.environ.get("SLEEVE_SHELF_PORT", "5000")),
    )
