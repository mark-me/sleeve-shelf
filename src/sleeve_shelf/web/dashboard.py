"""Dashboard: the collection at a glance, and what is waiting for a decision."""

from flask import Blueprint, redirect, render_template, url_for

from sleeve_shelf.alias_groups import family_suggestions
from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    Cabinet,
    Cluster,
    MatchProposal,
    Placement,
    Shelf,
    UnitType,
)
from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.proposal import has_proposal, takes_part
from sleeve_shelf.versions import list_versions
from sleeve_shelf.web.context import get_store, has_collection

blueprint = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@blueprint.before_request
def require_collection():
    if not has_collection():
        return redirect(url_for("setup.welcome"))


@blueprint.get("/")
def index():
    store = get_store()
    albums = store.load(Album)
    artists = store.load(Artist)
    shelves = store.load(Shelf)
    placed = {p.unit_id for p in store.load(Placement) if p.unit_type is UnitType.ALBUM}
    sorted_albums = [album for album in albums if takes_part(album, placed)]
    sorted_artists = {album.artist_id for album in sorted_albums}
    confirmed = {a.artist_id for a in store.load(ArtistClusterAssignment) if a.confirmed}
    start_years = {artist.id for artist in artists if artist.start_year}
    fill = BrowseQueries(store).shelf_fill()
    versions = list_versions(store)

    waiting = [
        {
            "count": len(store.load(MatchProposal)),
            "kind": "matches",
            "url": url_for("discogs.index") + "#matches",
        },
        {
            "count": len(family_suggestions(store)),
            "kind": "families",
            "url": url_for("families.index"),
        },
        {
            "count": sum(
                1 for a in sorted_artists if a not in confirmed or a not in start_years
            ),
            "kind": "artists",
            "url": url_for("artists.index", show="attention"),
        },
        {
            "count": sum(1 for album in sorted_albums if not album.width_confirmed),
            "kind": "widths",
            "url": url_for("albums.widths"),
        },
        {
            "count": sum(1 for album in sorted_albums if album.release_id is None),
            "kind": "unlinked",
            "url": url_for("discogs.index"),
        },
        {
            "count": sum(
                1 for s in shelves if s.width_cm and fill.get(s.id, (0, 0.0))[1] > s.width_cm
            ),
            "kind": "overfull",
            "url": url_for("storage.index"),
        },
        {
            "count": sum(1 for album in sorted_albums if album.id not in placed),
            "kind": "unplaced",
            "url": url_for("browse.unplaced"),
        },
    ]
    return render_template(
        "dashboard/index.html",
        album_count=len(sorted_albums),
        placed_count=len(placed),
        single_count=len(albums) - len(sorted_albums),
        artist_count=len(sorted_artists),
        cluster_count=len(store.load(Cluster)),
        cabinet_count=len(store.load(Cabinet)),
        shelf_count=len(shelves),
        waiting=[item for item in waiting if item["count"]],
        has_proposal=has_proposal(store),
        last_version=versions[0] if versions else None,
        unsaved=not any(version.is_current for version in versions),
    )
