"""Albums: the page of one album, moving it, and the real width of box sets and bundles."""

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_babel import gettext as _

from sleeve_shelf.domain import Album, Artist, Placement, Style
from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.placing import move_albums
from sleeve_shelf.proposal import takes_part
from sleeve_shelf.web.context import get_store, has_collection
from sleeve_shelf.web.places import described_rules, shelf_options

blueprint = Blueprint("albums", __name__, url_prefix="/albums")


@blueprint.before_request
def require_collection():
    if not has_collection():
        return redirect(url_for("setup.welcome"))


@blueprint.get("/<int:album_id>")
def detail(album_id: int):
    store = get_store()
    album = next((a for a in store.load(Album) if a.id == album_id), None)
    if album is None:
        abort(404)
    artist = next((a for a in store.load(Artist) if a.id == album.artist_id), None)
    # Where the album stands, with its cluster and era band, comes from the same query as Browse.
    row = next(
        (r for r in BrowseQueries(store).artist_albums(album.artist_id) if r.album_id == album_id),
        None,
    )
    style_names = {style.id: style.name for style in store.load(Style)}
    placed = {p.album_id for p in store.load(Placement)}
    return render_template(
        "albums/detail.html",
        album=album,
        artist=artist,
        row=row,
        styles=[style_names[i] for i in album.style_ids if i in style_names],
        takes_part=takes_part(album, placed),
        rules=described_rules(store, album.artist_id, album_id),
        shelves=shelf_options(store),
        moved=request.args.get("moved"),
        error=request.args.get("error"),
    )


@blueprint.post("/<int:album_id>/move")
def move(album_id: int):
    store = get_store()
    if all(album.id != album_id for album in store.load(Album)):
        abort(404)
    shelf_id = request.form.get("shelf_id", type=int)
    if shelf_id is not None and all(option["id"] != shelf_id for option in shelf_options(store)):
        abort(404)
    move_albums(store, [album_id], shelf_id)
    return redirect(url_for("albums.detail", album_id=album_id, moved=1))


@blueprint.get("/widths")
def widths():
    store = get_store()
    artists = {artist.id: artist.name for artist in store.load(Artist)}
    placed = {p.album_id for p in store.load(Placement)}
    rows = sorted(
        (
            {"album": album, "artist": artists.get(album.artist_id, "")}
            for album in store.load(Album)
            if takes_part(album, placed)
            and (not album.width_confirmed or album.manual_width_cm is not None)
        ),
        key=lambda row: (row["artist"].casefold(), row["album"].title.casefold()),
    )
    return render_template(
        "albums/widths.html",
        to_measure=[row for row in rows if row["album"].manual_width_cm is None],
        measured=[row for row in rows if row["album"].manual_width_cm is not None],
        error=request.args.get("error"),
    )


@blueprint.post("/<int:album_id>/width")
def set_width(album_id: int):
    store = get_store()
    text = request.form.get("width_cm", "").strip().replace(",", ".")
    try:
        width = float(text) if text else None
    except ValueError:
        width = -1
    # The form on an album's own page sends the visitor back there.
    on_album = request.form.get("next") == "album"
    if width is not None and width <= 0:
        message = _("A width has to be a number of centimetres above zero.")
        if on_album:
            return redirect(url_for("albums.detail", album_id=album_id, error=message))
        return redirect(url_for("albums.widths", error=message) + f"#album-{album_id}")
    albums = store.load(Album)
    for album in albums:
        if album.id == album_id:
            # An empty width goes back to the estimate; a compound format then awaits one again.
            album.manual_width_cm = width
            compound = bool(album.format_tokens and album.format_tokens.is_compound)
            album.width_confirmed = width is not None or not compound
    store.save(Album, albums)
    if on_album:
        return redirect(url_for("albums.detail", album_id=album_id))
    return redirect(url_for("albums.widths") + f"#album-{album_id}")
