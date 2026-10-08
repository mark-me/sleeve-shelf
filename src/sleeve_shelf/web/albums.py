"""Album widths: entering the real width of box sets, bundles, and anything else."""

from flask import Blueprint, redirect, render_template, request, url_for
from flask_babel import gettext as _

from sleeve_shelf.domain import Album, Artist, Placement, UnitType
from sleeve_shelf.proposal import takes_part
from sleeve_shelf.web.context import get_store, has_collection

blueprint = Blueprint("albums", __name__, url_prefix="/albums")


@blueprint.before_request
def require_collection():
    if not has_collection():
        return redirect(url_for("setup.welcome"))


@blueprint.get("/widths")
def widths():
    store = get_store()
    artists = {artist.id: artist.name for artist in store.load(Artist)}
    placed = {p.unit_id for p in store.load(Placement) if p.unit_type is UnitType.ALBUM}
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
    if width is not None and width <= 0:
        return redirect(
            url_for("albums.widths", error=_("A width has to be a number of centimetres above zero."))
            + f"#album-{album_id}"
        )
    albums = store.load(Album)
    for album in albums:
        if album.id == album_id:
            # An empty width goes back to the estimate; a compound format then awaits one again.
            album.manual_width_cm = width
            compound = bool(album.format_tokens and album.format_tokens.is_compound)
            album.width_confirmed = width is not None or not compound
    store.save(Album, albums)
    return redirect(url_for("albums.widths") + f"#album-{album_id}")
