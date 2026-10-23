"""Artists: the list, and curating one artist's start year and cluster."""

import unicodedata
from collections import defaultdict
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

from sleeve_shelf import artists as artist_service
from sleeve_shelf.alias_groups import cluster_hints
from sleeve_shelf.artists import (
    PICTURE_DIR,
    albums_per_artist,
    picture_thumb,
    remove_picture,
    set_picture,
)
from sleeve_shelf.domain import (
    Album,
    AliasGroup,
    Artist,
    ArtistClusterAssignment,
    ArtistEnrichment,
    Cluster,
    Style,
    find_by_id,
)
from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.shifts import cluster_shifts, keep_cluster
from sleeve_shelf.sorting.connections import connections_of
from sleeve_shelf.sorting.eras import band_of
from sleeve_shelf.sorting.families import sort_name
from sleeve_shelf.sorting.order import propose_cluster
from sleeve_shelf.taking_part import albums_taking_part
from sleeve_shelf.web.context import get_store
from sleeve_shelf.web.login import redirect_within
from sleeve_shelf.web.places import described_rules

blueprint = Blueprint("artists", __name__, url_prefix="/artists")


def _albums_taking_part(store) -> dict[int, list[Album]]:
    by_artist: dict[int, list[Album]] = defaultdict(list)
    for album in albums_taking_part(store):
        by_artist[album.artist_id].append(album)
    return by_artist


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


def _earliest_year(albums: list[Album]) -> int | None:
    return min((a.original_release_year for a in albums if a.original_release_year), default=None)


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
    by_artist = _albums_taking_part(store)
    album_counts = albums_per_artist(store)
    cluster_names = {cluster.id: cluster.name for cluster in store.load(Cluster)}
    assignments = {a.artist_id: a for a in store.load(ArtistClusterAssignment)}
    families = {group.id: group.label for group in store.load(AliasGroup)}
    pictures = {
        picture.discogs_artist_id: picture.thumb_url for picture in store.load(ArtistEnrichment)
    }

    def picture_of(artist: Artist) -> str | None:
        # The user's own picture goes before the one from Discogs.
        if artist.picture_file:
            # The small copy: a list never loads a picture in full.
            return url_for("artists.picture", name=picture_thumb(store, artist))
        return pictures.get(artist.discogs_artist_id)


    shifts = {shift.artist_id: shift for shift in cluster_shifts(store)}

    rows = []
    for artist in artists:
        if by_letter and initial(artist.name) != letter:
            continue
        assignment = assignments.get(artist.id)
        sorted_albums = by_artist.get(artist.id, [])
        # Only artists that are sorted need a cluster and a start year.
        shift = shifts.get(artist.id)
        attention = shift is not None or bool(sorted_albums) and (
            assignment is None or not assignment.confirmed or artist.start_year is None
        )
        if (search and search not in artist.name.casefold()) or (only_attention and not attention):
            continue
        if cluster_filter is not None and (assignment is None or assignment.cluster_id != cluster_filter):
            continue
        rows.append(
            {
                "artist": artist,
                "picture": picture_of(artist),
                "albums": album_counts[artist.id],
                "cluster": cluster_names.get(assignment.cluster_id) if assignment else None,
                "cluster_confirmed": bool(assignment and assignment.confirmed),
                "derived_year": _earliest_year(sorted_albums),
                "family": families.get(artist.alias_group_id),
                "attention": attention,
                "shift_to": cluster_names.get(shift.proposed_cluster_id) if shift else None,
                "sorted": bool(sorted_albums),
            }
        )
    rows.sort(key=lambda row: sort_name(row["artist"].name))
    return render_template(
        "artists/index.html",
        rows=rows,
        search_text=request.args.get("q", "").strip(),
        only_attention=only_attention,
        cluster_name=cluster_names.get(cluster_filter),
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
            return redirect(url_for("artists.edit", artist_id=artist_id, saved=1))

    albums = [album for album in store.load(Album) if album.artist_id == artist_id]
    sorted_albums = _albums_taking_part(store).get(artist_id, [])
    clusters = sorted(
        store.load(Cluster), key=lambda c: (c.position if c.position is not None else 10**6, c.id)
    )
    assignment = next(
        (a for a in store.load(ArtistClusterAssignment) if a.artist_id == artist_id), None
    )
    proposed_id = propose_cluster(sorted_albums, {style.id: style for style in store.load(Style)})
    all_artists = store.load(Artist)
    cluster_of = {
        a.artist_id: a.cluster_id for a in store.load(ArtistClusterAssignment)
    }
    connections = connections_of(artist_id, all_artists, store.load(ArtistEnrichment))

    def related(artist_ids: tuple[int, ...]) -> list[dict]:
        found = [a for a in all_artists if a.id in artist_ids]
        return [
            {"id": a.id, "name": a.name, "cluster": cluster_names.get(cluster_of.get(a.id))}
            for a in sorted(found, key=lambda a: sort_name(a.name))
        ]

    # Whom Discogs connects the artist to goes before its styles, when the connection is close.
    hint = cluster_hints(store).get(artist_id)
    names = {a.id: a.name for a in store.load(Artist)}
    located = {row.album_id: row for row in BrowseQueries(store).artist_albums(artist_id)}
    family = find_by_id(store.load(AliasGroup), artist.alias_group_id)
    derived_year = _earliest_year(sorted_albums)
    shift = next((s for s in cluster_shifts(store) if s.artist_id == artist_id), None)
    cluster_names = {cluster.id: cluster.name for cluster in clusters}
    return (
        render_template(
            "artists/edit.html",
            artist=artist,
            picture=_picture(store, artist),
            picture_error=request.args.get("picture_error"),
            errors=errors,
            shift=shift
            and {
                "current": cluster_names.get(shift.cluster_id),
                "proposed": cluster_names.get(shift.proposed_cluster_id),
                "titles": [album.title for album in albums if album.id in shift.album_ids],
            },
            saved=request.args.get("saved") and not errors,
            clusters=clusters,
            assignment=assignment,
            proposed_cluster=find_by_id(clusters, proposed_id),
            connected_cluster=find_by_id(clusters, hint.cluster_id if hint else None),
            connection_decides=bool(hint and hint.decisive),
            related={
                "other_names": related(connections.other_names),
                "bands": related(connections.bands),
                "members": related(connections.members),
            },
            connected_artists=[
                {"id": other_id, "name": names[other_id]}
                for other_id in (hint.via_artist_ids if hint else ())
            ],
            derived_year=derived_year,
            band=band_of(artist.start_year or derived_year),
            family=family,
            rules=described_rules(store, artist_id),
            moved=request.args.get("moved"),
            wikipedia_url="https://en.wikipedia.org/wiki/Special:Search?search="
            + quote(sort_name(artist.name)),
            albums=sorted(
                (
                    {"album": album, "place": located.get(album.id)}
                    for album in albums
                ),
                key=lambda row: (row["album"].original_release_year or 9999, row["album"].title.casefold()),
            ),
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
    return redirect_within(request.form.get("next"), url_for("artists.edit", artist_id=artist_id))


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
    return redirect(url_for("artists.edit", artist_id=artist_id, picture_error=error))


@blueprint.post("/<int:artist_id>/picture/remove")
def delete_picture(artist_id: int):
    remove_picture(get_store(), artist_id)
    return redirect(url_for("artists.edit", artist_id=artist_id))
