"""Which one is this: a photo of a sleeve, and where that album stands."""

from flask import Blueprint, abort, render_template, request

from sleeve_shelf.domain import Album
from sleeve_shelf.fetching.recognition import MAX_PHOTO_BYTES, recognise
from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.web.context import get_store
from sleeve_shelf.web.login import visitor_may_recognise

blueprint = Blueprint("recognise", __name__, url_prefix="/recognise")


@blueprint.post("/")
def photo():
    """The album a photo shows, with where it stands; or the likeliest ones to choose from."""
    if not visitor_may_recognise():
        abort(429)
    sent = request.files.get("photo")
    # Read one byte past the limit, so a photo too large is told from one just within it.
    data = sent.stream.read(MAX_PHOTO_BYTES + 1) if sent else b""
    found = recognise(get_store(), data) if data else None
    if found is None or not found.readable:
        return render_template("recognise/result.html", unreadable=True), 400
    if found.sure:
        return _where(found.album_ids[0], recognised=True)
    rows = BrowseQueries(get_store()).albums(found.album_ids)
    return render_template("recognise/result.html", choices=[rows[i] for i in found.album_ids if i in rows])


@blueprint.get("/<int:album_id>")
def where(album_id: int):
    """Where an album stands, chosen among those a photo may show.

    Args:
        album_id: The album.
    """
    return _where(album_id, recognised=False)


def _where(album_id: int, recognised: bool):
    """The page saying where the album stands, and between which albums."""
    store = get_store()
    if all(album.id != album_id for album in store.load(Album)):
        abort(404)
    queries = BrowseQueries(store)
    before, after = queries.neighbours(album_id)
    return render_template(
        "recognise/result.html",
        album=queries.albums([album_id])[album_id],
        before=before,
        after=after,
        recognised=recognised,
    )
