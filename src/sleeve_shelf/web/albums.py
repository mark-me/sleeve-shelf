"""Albums: the page of one album, moving it, and the real width of box sets and bundles."""

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_babel import gettext as _

from sleeve_shelf.config import load_settings
from sleeve_shelf.domain import (
    Album,
    Artist,
    Placement,
    ReleaseEnrichment,
    Style,
    find_by_id,
)
from sleeve_shelf.ingestion.deezer import DeezerClient
from sleeve_shelf.ingestion.discogs_api import DiscogsClient
from sleeve_shelf.listening import listening, turn_down
from sleeve_shelf.network import album_songs_elsewhere
from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.spots import place_at_spot
from sleeve_shelf.taking_part import albums_taking_part, takes_part
from sleeve_shelf.web.context import get_store, parse_number
from sleeve_shelf.web.login import visitor_may_listen
from sleeve_shelf.web.places import described_rules, described_spots
from sleeve_shelf.widths import set_measured_width

blueprint = Blueprint("albums", __name__, url_prefix="/albums")


@blueprint.get("/<int:album_id>")
def detail(album_id: int):
    store = get_store()
    album = find_by_id(store.load(Album), album_id)
    if album is None:
        abort(404)
    artist = find_by_id(store.load(Artist), album.artist_id)
    # Where the album stands, with its cluster and era band, comes from the same query as Browse.
    row = next(
        (r for r in BrowseQueries(store).artist_albums(album.artist_id) if r.album_id == album_id),
        None,
    )
    style_names = {style.id: style.name for style in store.load(Style)}
    placed = {p.album_id for p in store.load(Placement)}
    release = next(
        (r for r in store.load(ReleaseEnrichment) if r.release_id == album.release_id), None
    )
    # The same songs on other albums of the collection, each album with where it stands.
    elsewhere = album_songs_elsewhere(store, album_id)
    if elsewhere:
        rows = {r.album_id: r for r in BrowseQueries(store).everything()}
        elsewhere = [(title, [rows[i] for i in others if i in rows]) for title, others in elsewhere]
    return render_template(
        "albums/detail.html",
        album=album,
        artist=artist,
        row=row,
        styles=[style_names[i] for i in album.style_ids if i in style_names],
        # None while the release was not fetched with its tracklist yet.
        tracklist=release.tracklist if release else None,
        elsewhere=elsewhere,
        takes_part=takes_part(album, placed),
        is_placed=album_id in placed,
        spot=None if album_id in placed else described_spots(store).get(album_id),
        placed=request.args.get("placed"),
        rules=described_rules(store, album.artist_id, album_id),
        moved=request.args.get("moved"),
        error=request.args.get("error"),
    )


@blueprint.get("/<int:album_id>/listen")
def listen(album_id: int):
    """The album's previews and videos, as a part the album's page loads after it is shown:
    the page itself never waits for Deezer or Discogs."""
    store = get_store()
    if not visitor_may_listen():
        return render_template("albums/_listen.html", album_id=album_id, listening=None), 429
    deezer = current_app.config.get("DEEZER_CLIENT_FACTORY", DeezerClient)()
    # Discogs answers a few lookups without a token too, at a lower rate.
    token = load_settings(current_app.config["DATA_DIR"]).discogs_token or ""
    discogs = current_app.config.get("DISCOGS_CLIENT_FACTORY", DiscogsClient)(token)
    found = listening(store, album_id, deezer, discogs)
    if found is None:
        abort(404)
    return render_template("albums/_listen.html", album_id=album_id, listening=found)


@blueprint.get("/<int:album_id>/previews")
def previews(album_id: int):
    """The album's previews from Deezer, for the play button in Browse. Discogs is not asked:
    its videos are for the album's page, and a shelf full of buttons should not wait on it."""
    if not visitor_may_listen():
        return jsonify(album=None, tracks=[], unreachable=False, busy=True), 429
    deezer = current_app.config.get("DEEZER_CLIENT_FACTORY", DeezerClient)()
    found = listening(get_store(), album_id, deezer, None)
    if found is None:
        abort(404)
    return jsonify(
        album=found.album.title if found.album else None,
        tracks=[{"title": t.title, "preview": t.preview} for t in found.tracks if t.preview],
        unreachable=found.unreachable,
    )


@blueprint.post("/<int:album_id>/listen/not-this")
def listen_not_this(album_id: int):
    """The album Deezer gave is another one: leave it out for this album."""
    turn_down(get_store(), album_id)
    return redirect(url_for("albums.detail", album_id=album_id) + "#listen")


@blueprint.post("/<int:album_id>/place")
def place(album_id: int):
    """Stand an album that waits for a place at its suggested spot."""
    store = get_store()
    if all(album.id != album_id for album in store.load(Album)):
        abort(404)
    spot = place_at_spot(store, album_id, load_settings(store.data_dir).width_constants)
    back = request.form.get("back")
    if back == "list":
        return redirect(url_for("browse.unplaced", placed=album_id if spot else None))
    if back == "dashboard":
        return redirect(url_for("dashboard.index", placed=album_id if spot else None))
    return redirect(url_for("albums.detail", album_id=album_id, placed=1 if spot else None))


@blueprint.get("/widths")
def widths():
    store = get_store()
    artists = {artist.id: artist.name for artist in store.load(Artist)}
    rows = sorted(
        (
            {"album": album, "artist": artists.get(album.artist_id, "")}
            for album in albums_taking_part(store)
            if not album.width_confirmed or album.manual_width_cm is not None
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
    text = request.form.get("width_cm", "").strip()
    width = parse_number(text) if text else None
    # The form on an album's own page sends the visitor back there.
    on_album = request.form.get("next") == "album"
    if text and (width is None or width <= 0):
        message = _("A width has to be a number of centimetres above zero.")
        if on_album:
            return redirect(url_for("albums.detail", album_id=album_id, error=message))
        return redirect(url_for("albums.widths", error=message) + f"#album-{album_id}")
    # An empty width goes back to the estimate.
    set_measured_width(store, album_id, width)
    if on_album:
        return redirect(url_for("albums.detail", album_id=album_id))
    return redirect(url_for("albums.widths") + f"#album-{album_id}")
