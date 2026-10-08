"""Dashboard: the collection at a glance, and what is waiting for a decision."""

from flask import Blueprint, redirect, render_template, url_for

from sleeve_shelf.domain import Album, Cabinet, Cluster, Placement, Shelf, UnitType
from sleeve_shelf.proposal import has_proposal, takes_part
from sleeve_shelf.versions import list_versions
from sleeve_shelf.web.context import get_store, has_collection
from sleeve_shelf.web.waiting import waiting_counts

blueprint = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@blueprint.before_request
def require_collection():
    if not has_collection():
        return redirect(url_for("setup.welcome"))


@blueprint.get("/")
def index():
    store = get_store()
    albums = store.load(Album)
    shelves = store.load(Shelf)
    placed = {p.unit_id for p in store.load(Placement) if p.unit_type is UnitType.ALBUM}
    sorted_albums = [album for album in albums if takes_part(album, placed)]
    sorted_artists = {album.artist_id for album in sorted_albums}
    versions = list_versions(store)
    counts = waiting_counts(store)
    urls = {
        "matches": url_for("discogs.index") + "#matches",
        "families": url_for("families.index"),
        "artists": url_for("artists.index", show="attention"),
        "widths": url_for("albums.widths"),
        "unlinked": url_for("discogs.index"),
        "gone": url_for("discogs.index") + "#gone",
        "overfull": url_for("storage.index"),
        "unplaced": url_for("browse.unplaced"),
    }
    waiting = [{"count": counts[kind], "kind": kind, "url": url} for kind, url in urls.items()]
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
