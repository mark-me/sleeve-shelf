"""Artists: the list, and curating one artist's start year and cluster."""

import unicodedata
from urllib.parse import quote

from flask import (
    Blueprint,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_babel import gettext as _

from sleeve_shelf.library import artists as artist_service
from sleeve_shelf.insights.collection_stats import artist_figures
from sleeve_shelf.library.artists import (
    PICTURE_DIR,
    picture_thumb,
    remove_picture,
    set_picture,
)
from sleeve_shelf.domain import (
    Artist,
    ArtistEnrichment,
    Cluster,
    find_by_id,
    sort_name,
)
from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.shelving.curation import artist_details, artist_rows
from sleeve_shelf.shelving.shifts import cluster_shifts, keep_cluster
from sleeve_shelf.web.context import get_store
from sleeve_shelf.web.login import is_owner, redirect_within

blueprint = Blueprint("artists", __name__, url_prefix="/artists")


# The list without a search is shown one letter at a time; "#" holds names that start with
# a digit or anything else.
LETTERS = ("#", *"ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def initial(name: str) -> str:
    """The letter a name is listed under: its first letter as sorted, accents left off."""
    for char in unicodedata.normalize("NFKD", sort_name(name)):
        if char.isalpha():
            return char.upper() if "A" <= char.upper() <= "Z" else "#"
        if char.isdigit():
            return "#"
    return "#"


@blueprint.get("/")
def index():
    store = get_store()
    search = request.args.get("q", "").strip().casefold()
    only_attention = request.args.get("show") == "attention"
    cluster_filter = request.args.get("cluster", type=int)
    artists = store.load(Artist)
    # Searching or filtering looks through everyone; otherwise one letter at a time.
    by_letter = not search and not only_attention and cluster_filter is None
    available = {initial(artist.name) for artist in artists}
    letter = request.args.get("letter", "").upper()
    if by_letter and letter not in available:
        letter = next((c for c in LETTERS[1:] if c in available), "#")
    pictures = {
        picture.discogs_artist_id: picture.thumb_url for picture in store.load(ArtistEnrichment)
    }

    def picture_of(artist: Artist) -> str | None:
        # The user's own picture goes before the one from Discogs.
        if artist.picture_file:
            # The small copy: a list never loads a picture in full.
            return url_for("artists.picture", name=picture_thumb(store, artist))
        return pictures.get(artist.discogs_artist_id)

    chosen = find_by_id(store.load(Cluster), cluster_filter)
    rows = [
        {**row, "picture": picture_of(row["artist"])}
        for row in artist_rows(store)
        if not (by_letter and initial(row["artist"].name) != letter)
        and not (search and search not in row["artist"].name.casefold())
        and not (only_attention and not row["attention"])
        and not (cluster_filter is not None and row["cluster_id"] != cluster_filter)
    ]
    return render_template(
        "artists/index.html",
        rows=rows,
        search_text=request.args.get("q", "").strip(),
        only_attention=only_attention,
        cluster_name=chosen.name if chosen else None,
        letters=[(c, c in available) for c in LETTERS] if by_letter else [],
        letter=letter if by_letter else None,
        total=len(artists),
    )


@blueprint.route("/<int:artist_id>", methods=["GET", "POST"])
def edit(artist_id: int):
    store = get_store()
    artist = find_by_id(store.load(Artist), artist_id)
    if artist is None:
        abort(404)
    errors: list[str] = []
    if request.method == "POST":
        year_text = request.form.get("start_year", "").strip()
        year = int(year_text) if year_text.isdigit() else None
        if year_text and (year is None or not 1000 <= year <= 2100):
            errors.append(_("The start year has to be a year, like 1969."))
        new_cluster = request.form.get("new_cluster", "").strip()
        cluster_id = request.form.get("cluster_id", type=int)
        if not errors:
            artist_service.set_start_year(store, artist_id, year)
            artist_service.set_cluster(store, artist_id, cluster_id, new_cluster)
            return redirect(url_for("artists.edit", artist_id=artist_id, tab="manage", saved=1))

    details = artist_details(store, artist)
    needs_attention = details.pop("needs_attention")
    # What the artist is comes first; what can be changed about it is the owner's, a tab further.
    owner = is_owner()
    tab = "manage" if owner and (errors or request.args.get("tab") == "manage") else "artist"
    return (
        render_template(
            "artists/edit.html",
            **details,
            tab=tab,
            # What waits for the owner here, said on the first tab too.
            attention=owner and needs_attention,
            figures=artist_figures(store, artist_id) if tab == "artist" else None,
            places={row.album_id: row for row in BrowseQueries(store).everything()} if tab == "artist" else {},
            artist=artist,
            picture=_picture(store, artist),
            picture_error=request.args.get("picture_error"),
            errors=errors,
            saved=request.args.get("saved") and not errors,
            moved=request.args.get("moved"),
            wikipedia_url="https://en.wikipedia.org/wiki/Special:Search?search="
            + quote(sort_name(artist.name)),
        ),
        400 if errors else 200,
    )


@blueprint.post("/<int:artist_id>/confirm")
def confirm(artist_id: int):
    artist_service.confirm_cluster(get_store(), artist_id)
    return redirect_within(request.form.get("next"), url_for("artists.index"))


@blueprint.post("/<int:artist_id>/shift/<any(accept, keep):choice>")
def decide_shift(artist_id: int, choice: str):
    """A new purchase points the artist to another cluster: move it there, or keep it where it is."""
    store = get_store()
    shift = next((s for s in cluster_shifts(store) if s.artist_id == artist_id), None)
    if shift is not None and choice == "accept":
        artist_service.set_cluster(store, artist_id, shift.proposed_cluster_id)
    elif shift is not None:
        keep_cluster(store, artist_id)
    return redirect_within(request.form.get("next"), url_for("artists.edit", artist_id=artist_id, tab="manage"))


def _picture(store, artist: Artist):
    """What the artist's page shows as its picture: the user's own, else the one from Discogs."""
    if artist.picture_file:
        return {
            "thumb_url": url_for("artists.picture", name=picture_thumb(store, artist)),
            "image_url": url_for("artists.picture", name=artist.picture_file),
            "own": True,
        }
    found = next(
        (
            picture
            for picture in store.load(ArtistEnrichment)
            if picture.discogs_artist_id == artist.discogs_artist_id
        ),
        None,
    )
    if found is None:
        return None
    return {"thumb_url": found.thumb_url, "image_url": found.image_url, "own": False}


@blueprint.get("/pictures/<name>")
def picture(name: str):
    """A picture the user added; its name changes with its contents, so it can be cached for long."""
    return send_from_directory(
        current_app.config["DATA_DIR"] / PICTURE_DIR, name, max_age=365 * 24 * 60 * 60
    )


@blueprint.post("/<int:artist_id>/picture")
def upload_picture(artist_id: int):
    file = request.files.get("picture")
    data = file.read() if file is not None and file.filename else b""
    error = None
    if not data:
        error = _("Choose an image to upload.")
    elif not set_picture(get_store(), artist_id, data):
        error = _("That file is not a JPEG, PNG, GIF or WebP image of at most 5 MB.")
    return redirect(url_for("artists.edit", artist_id=artist_id, tab="manage", picture_error=error))


@blueprint.post("/<int:artist_id>/picture/remove")
def delete_picture(artist_id: int):
    remove_picture(get_store(), artist_id)
    return redirect(url_for("artists.edit", artist_id=artist_id, tab="manage"))
