"""Covers: the album covers and artist pictures kept in the data directory."""

from flask import Blueprint, abort, current_app, g, send_from_directory, url_for

from sleeve_shelf.covers import COVER_DIR, cover_name, stored_names

blueprint = Blueprint("covers", __name__, url_prefix="/covers")

# A file is named after the address of its image, so it never changes.
CACHE_SECONDS = 365 * 24 * 60 * 60


@blueprint.get("/<name>")
def file(name: str):
    if not name.endswith(".jpg"):
        abort(404)
    return send_from_directory(
        current_app.config["DATA_DIR"] / COVER_DIR, name, max_age=CACHE_SECONDS
    )


def local_cover(url: str | None) -> str | None:
    """The address a page shows an image from: the stored copy when there is one, else Discogs."""
    if not url:
        return url
    if "cover_names" not in g:
        g.cover_names = stored_names(current_app.config["DATA_DIR"])
    name = cover_name(url)
    return url_for("covers.file", name=name) if name in g.cover_names else url
