"""Artists: the list, and curating one artist's start year and cluster."""

from collections import Counter, defaultdict
from urllib.parse import quote

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_babel import gettext as _

from sleeve_shelf import artists as artist_service
from sleeve_shelf.domain import (
    Album,
    AliasGroup,
    Artist,
    ArtistClusterAssignment,
    ArtistEnrichment,
    Cluster,
    Placement,
    Style,
)
from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.placing import move_albums
from sleeve_shelf.proposal import takes_part
from sleeve_shelf.shifts import cluster_shifts, keep_cluster
from sleeve_shelf.sorting.eras import band_of
from sleeve_shelf.sorting.families import sort_name
from sleeve_shelf.sorting.order import propose_cluster
from sleeve_shelf.web.context import get_store, has_collection
from sleeve_shelf.web.places import described_rules, shelf_options

blueprint = Blueprint("artists", __name__, url_prefix="/artists")


@blueprint.before_request
def require_collection():
    if not has_collection():
        return redirect(url_for("setup.welcome"))


def _albums_taking_part(store) -> dict[int, list[Album]]:
    placed = {p.album_id for p in store.load(Placement)}
    by_artist: dict[int, list[Album]] = defaultdict(list)
    for album in store.load(Album):
        if takes_part(album, placed):
            by_artist[album.artist_id].append(album)
    return by_artist


def _earliest_year(albums: list[Album]) -> int | None:
    return min((a.original_release_year for a in albums if a.original_release_year), default=None)


@blueprint.get("/")
def index():
    store = get_store()
    search = request.args.get("q", "").strip().casefold()
    only_attention = request.args.get("show") == "attention"
    cluster_filter = request.args.get("cluster", type=int)
    by_artist = _albums_taking_part(store)
    album_counts = Counter(album.artist_id for album in store.load(Album))
    cluster_names = {cluster.id: cluster.name for cluster in store.load(Cluster)}
    assignments = {a.artist_id: a for a in store.load(ArtistClusterAssignment)}
    families = {group.id: group.label for group in store.load(AliasGroup)}
    pictures = {
        picture.discogs_artist_id: picture.thumb_url for picture in store.load(ArtistEnrichment)
    }

    shifts = {shift.artist_id: shift for shift in cluster_shifts(store)}

    rows = []
    for artist in store.load(Artist):
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
                "picture": pictures.get(artist.discogs_artist_id),
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
    )


@blueprint.route("/<int:artist_id>", methods=["GET", "POST"])
def edit(artist_id: int):
    store = get_store()
    artist = next((a for a in store.load(Artist) if a.id == artist_id), None)
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
    located = {row.album_id: row for row in BrowseQueries(store).artist_albums(artist_id)}
    family = next((g for g in store.load(AliasGroup) if g.id == artist.alias_group_id), None)
    derived_year = _earliest_year(sorted_albums)
    shift = next((s for s in cluster_shifts(store) if s.artist_id == artist_id), None)
    cluster_names = {cluster.id: cluster.name for cluster in clusters}
    return (
        render_template(
            "artists/edit.html",
            artist=artist,
            picture=next(
                (
                    picture
                    for picture in store.load(ArtistEnrichment)
                    if picture.discogs_artist_id == artist.discogs_artist_id
                ),
                None,
            ),
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
            proposed_cluster=next((c for c in clusters if c.id == proposed_id), None),
            derived_year=derived_year,
            band=band_of(artist.start_year or derived_year),
            family=family,
            rules=described_rules(store, artist_id),
            shelves=shelf_options(store),
            movable_count=len(sorted_albums),
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


@blueprint.post("/<int:artist_id>/move")
def move(artist_id: int):
    """Stand all the artist's albums that take part on one shelf, in year and title order."""
    store = get_store()
    shelf_id = request.form.get("shelf_id", type=int)
    if shelf_id is not None and all(option["id"] != shelf_id for option in shelf_options(store)):
        abort(404)
    albums = sorted(
        _albums_taking_part(store).get(artist_id, []),
        key=lambda album: (album.original_release_year or 9999, album.title.casefold()),
    )
    move_albums(store, [album.id for album in albums], shelf_id)
    return redirect(url_for("artists.edit", artist_id=artist_id, moved=1))


@blueprint.post("/<int:artist_id>/confirm")
def confirm(artist_id: int):
    artist_service.confirm_cluster(get_store(), artist_id)
    return redirect(request.form.get("next") or url_for("artists.index"))


@blueprint.post("/<int:artist_id>/shift/<any(accept, keep):choice>")
def decide_shift(artist_id: int, choice: str):
    """A new purchase points the artist to another cluster: move it there, or keep it where it is."""
    store = get_store()
    shift = next((s for s in cluster_shifts(store) if s.artist_id == artist_id), None)
    if shift is not None and choice == "accept":
        artist_service.set_cluster(store, artist_id, shift.proposed_cluster_id)
    elif shift is not None:
        keep_cluster(store, artist_id)
    return redirect(request.form.get("next") or url_for("artists.edit", artist_id=artist_id))
