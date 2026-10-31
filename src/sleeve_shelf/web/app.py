"""The application factory: the Flask app with its blueprints, filters and guards."""

import logging
import os
import threading
from datetime import timedelta
from pathlib import Path

from flask import Flask, redirect, request, url_for
from flask_babel import Babel, get_locale
from werkzeug.middleware.proxy_fix import ProxyFix

from sleeve_shelf.access import has_password, session_key
from sleeve_shelf.config import data_directory, protect_settings
from sleeve_shelf.fetching.covers import COVER_DIR, sharpen_small_images, sort_into_folders
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.web import (
    albums,
    artists,
    browse,
    clusters,
    connections,
    covers,
    dashboard,
    discogs,
    families,
    language,
    layout,
    login,
    moving,
    navigation,
    pwa,
    rules,
    security,
    settings,
    setup,
    showcase,
    stats,
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
    {"albums", "artists", "browse", "clusters", "connections", "dashboard", "layout", "moving", "proposal", "showcase", "stats", "versions"}
)


def create_app(data_dir: str | Path | None = None) -> Flask:
    """Create and configure the Flask application instance."""
    # Named after the package: its folders and the name in the log are those of the whole app.
    app = Flask("sleeve_shelf", template_folder="web/templates", static_folder="web/static")
    app.config["DATA_DIR"] = data_directory(data_dir)
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
        os.environ.get("SLEEVE_SHELF_HELP_DIR") or Path(__file__).resolve().parents[3] / "docs-site" / "site"
    )
    # The browser's language, or the one chosen for this device under Settings.
    language.compile_catalogues()
    Babel(app, default_locale=language.DEFAULT, locale_selector=language.select)
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
    app.register_blueprint(moving.blueprint)
    app.register_blueprint(connections.blueprint)
    app.register_blueprint(stats.blueprint)
    app.register_blueprint(language.blueprint)
    app.add_template_filter(covers.local_cover, "local_cover")
    app.add_template_filter(language.decimal, "decimal")
    app.add_template_filter(language.editable, "editable")

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
            "language": str(get_locale()),
            "languages": language.LANGUAGES,
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
