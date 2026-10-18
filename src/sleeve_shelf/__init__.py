"""Sleeve & Shelf: application factory."""

import argparse
import getpass
import logging
import os
import threading
from datetime import timedelta
from pathlib import Path

from flask import Flask, redirect, request, url_for
from flask_babel import Babel
from werkzeug.middleware.proxy_fix import ProxyFix

from sleeve_shelf.access import has_password, remove_password, session_key, set_password
from sleeve_shelf.artists import set_picture
from sleeve_shelf.collection import load_layout
from sleeve_shelf.config import load_settings, protect_settings
from sleeve_shelf.covers import COVER_DIR, sharpen_small_images, sort_into_folders
from sleeve_shelf.discogs_import import import_discogs_collection
from sleeve_shelf.domain import Artist
from sleeve_shelf.enrichment import enrich_collection
from sleeve_shelf.ingestion.discogs_api import DiscogsClient, DiscogsError
from sleeve_shelf.ingestion.discogs_csv import read_collection
from sleeve_shelf.ingestion.initial_load import load_initial_layout
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.web import (
    albums,
    artists,
    browse,
    clusters,
    covers,
    dashboard,
    discogs,
    families,
    layout,
    login,
    navigation,
    pwa,
    rules,
    security,
    settings,
    setup,
    showcase,
    storage,
    versions,
)
from sleeve_shelf.web import help as help_screen
from sleeve_shelf.web import proposal as proposal_screen
from sleeve_shelf.web.context import get_store, has_collection
from sleeve_shelf.web.help import help_url
from sleeve_shelf.web.waiting import menu_counts

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


# The blueprints whose screens need a collection; the others work without one (the wizard,
# cabinets and shelves, Discogs, families, rules, settings, and the files the pages use).
NEEDS_COLLECTION = frozenset(
    {"albums", "artists", "browse", "clusters", "dashboard", "layout", "proposal", "showcase", "versions"}
)


def create_app(data_dir: str | Path | None = None) -> Flask:
    """Create and configure the Flask application instance."""
    app = Flask(__name__, template_folder="web/templates", static_folder="web/static")
    app.config["DATA_DIR"] = _data_dir(data_dir)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    # The owner's login: signed with a key of this installation, sent over HTTPS only (the
    # app is reachable from the internet), kept until logging out.
    app.secret_key = session_key(app.config["DATA_DIR"])
    protect_settings(app.config["DATA_DIR"])
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SLEEVE_SHELF_HTTP_LOGIN") != "1"
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=365)
    # How many proxies stand before the app and may say who the client is (Tailscale Funnel or
    # a reverse proxy: 1). Without, a forwarded address is not believed, as a client could
    # make one up to escape the limits on logging in and listening.
    proxies = int(os.environ.get("SLEEVE_SHELF_PROXIES") or 0)
    if proxies:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxies, x_proto=proxies, x_host=proxies)
    # Set by the Docker image build; a local run has no version.
    app.config["VERSION"] = os.environ.get("SLEEVE_SHELF_VERSION", "dev")
    # The built documentation site: carried by the Docker image, or built in the repository.
    app.config["HELP_DIR"] = Path(
        os.environ.get("SLEEVE_SHELF_HELP_DIR") or Path(__file__).resolve().parents[2] / "docs-site" / "site"
    )
    Babel(app, default_locale="en")
    # Logins, failed ones and visitors held up go to the log (the container's output).
    app.logger.setLevel(logging.INFO)
    if any(path.is_file() for path in (app.config["DATA_DIR"] / COVER_DIR).glob("*")):
        # Images stored before covers and pictures each had a folder: sort them out once.
        sort_into_folders(JsonStore(app.config["DATA_DIR"]))
    if (app.config["DATA_DIR"] / COVER_DIR).is_dir():
        # Small images stored as Discogs gives them are grainy: make them afresh from the
        # large ones. Done aside, as it takes a while the first time and the pages do not
        # wait for it; it fetches nothing, and there is nothing left to do afterwards.
        threading.Thread(
            target=lambda: sharpen_small_images(JsonStore(app.config["DATA_DIR"])), daemon=True
        ).start()

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
    app.register_blueprint(showcase.blueprint)
    app.register_blueprint(clusters.blueprint)
    app.register_blueprint(versions.blueprint)
    app.register_blueprint(dashboard.blueprint)
    app.register_blueprint(albums.blueprint)
    app.register_blueprint(pwa.blueprint)
    app.register_blueprint(covers.blueprint)
    app.register_blueprint(help_screen.blueprint)
    app.register_blueprint(login.blueprint)
    app.add_template_filter(covers.local_cover, "local_cover")

    # A visitor may only look the collection up; this runs before anything else.
    # A change sent from another site is refused before anything else looks at it.
    app.before_request(security.reject_other_sites)
    app.before_request(login.guard)
    app.after_request(security.add_headers)
    # Every template, also a macro imported from another, can mark its inline script.
    app.jinja_env.globals["csp_nonce"] = security.csp_nonce

    @app.before_request
    def require_collection():
        # Screens that show or change the collection lead to the wizard until there is one.
        if request.blueprint in NEEDS_COLLECTION and not has_collection():
            return redirect(url_for("setup.welcome"))

    @app.context_processor
    def menu():
        # The numbers behind menu items: where something is waiting for the user.
        # Before there is a collection the wizard leads, without menu or tabs.
        section, tab = navigation.current(request) if has_collection() else (None, None)
        owner = login.is_owner()
        visible = navigation.visible_sections(owner)
        # The tabs above the page, too, are those the one looking may use.
        section = next((s for s in visible if section and s.key == section.key), None)
        return {
            # A visitor is never shown what waits for the owner, nor the owner's screens.
            "menu_counts": menu_counts(get_store()) if has_collection() and owner else {},
            "nav_sections": visible,
            "is_owner": owner,
            "has_password": has_password(app.config["DATA_DIR"]),
            "nav_section": section,
            "nav_tab": tab,
            "section_count": navigation.section_count,
            # The part of the user guide that explains this page.
            "help_url": help_url(navigation.help_target(request, section, tab)),
        }

    @app.get("/")
    def index():
        if not has_collection():
            return redirect(url_for("setup.welcome"))
        return redirect(url_for("dashboard.index" if login.is_owner() else "browse.browse"))

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
    commands.add_parser("enrich", help="fetch styles, original years, tracklists and pictures from Discogs")
    set_picture_command = commands.add_parser(
        "set-picture", help="add your own picture of an artist, for when a browser can't upload"
    )
    set_picture_command.add_argument("artist")
    set_picture_command.add_argument("image", type=Path)
    password_command = commands.add_parser(
        "set-password", help="set the owner's password (also when it was forgotten); visitors may then only look"
    )
    password_command.add_argument("--remove", action="store_true", help="open the app again: no password")
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

    if options.command == "set-picture":
        name = options.artist.casefold()
        artist = next((a for a in store.load(Artist) if a.name.casefold() == name), None)
        if artist is None:
            parser.exit(1, f"No artist is called {options.artist!r}\n")
        if not set_picture(store, artist.id, options.image.read_bytes()):
            parser.exit(1, "That file is not a JPEG, PNG, GIF or WebP image of at most 5 MB\n")
        print(f"Picture of {artist.name} set")
        return

    if options.command == "set-password":
        if options.remove:
            remove_password(data_dir)
            print("Password removed: the app is open, everyone can change everything.")
            return
        password = getpass.getpass("New password: ")
        if password != getpass.getpass("Again: "):
            parser.exit(1, "The two passwords differ\n")
        try:
            set_password(data_dir, password)
        except ValueError as error:
            parser.exit(1, f"{error}\n")
        print("Password set: visitors may look the collection up; changing it needs the login.")
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
