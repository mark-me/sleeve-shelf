"""Installing the app on a phone or desktop: the web app manifest."""

from flask import Blueprint, jsonify, url_for
from flask_babel import gettext as _

blueprint = Blueprint("pwa", __name__)

BACKGROUND = "#1E293B"


@blueprint.get("/manifest.webmanifest")
def manifest():
    """Name, icons and start page of the installed app; it opens on Browse/Search.

    There is no service worker: every page comes from the server, so there is
    nothing to show without it, and browsers no longer need one to install an app.
    """

    def icon(filename: str, size: int, purpose: str) -> dict:
        return {
            "src": url_for("static", filename=f"icons/{filename}"),
            "sizes": f"{size}x{size}",
            "type": "image/png",
            "purpose": purpose,
        }

    response = jsonify(
        name="Sleeve & Shelf",
        short_name="Sleeve & Shelf",
        description=_("Your vinyl collection, in the order of your shelves."),
        start_url=url_for("browse.browse"),
        scope=url_for("index"),
        display="standalone",
        background_color=BACKGROUND,
        theme_color=BACKGROUND,
        icons=[
            icon("icon-192.png", 192, "any"),
            icon("icon-512.png", 512, "any"),
            icon("icon-maskable-512.png", 512, "maskable"),
        ],
    )
    response.mimetype = "application/manifest+json"
    return response
