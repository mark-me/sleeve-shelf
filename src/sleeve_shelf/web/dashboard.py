"""Dashboard: the collection at a glance, and what is waiting for a decision."""

from flask import Blueprint, redirect, render_template, url_for

from sleeve_shelf.domain import (
    Album,
    Cabinet,
    Cluster,
    LocationRule,
    Placement,
    ReleaseEnrichment,
    Shelf,
    UnitType,
)
from sleeve_shelf.proposal import has_proposal, takes_part
from sleeve_shelf.versions import list_versions
from sleeve_shelf.web.context import get_store, has_collection
from sleeve_shelf.web.waiting import waiting_counts

blueprint = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@blueprint.before_request
def require_collection():
    if not has_collection():
        return redirect(url_for("setup.welcome"))


def _countable(open_count: int, albums: list[Album]) -> dict:
    return {"open": open_count} if albums else {"later": True}


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
    cluster_count = len(store.load(Cluster))
    fetched = {release.release_id for release in store.load(ReleaseEnrichment)}
    to_fetch = len({a.release_id for a in albums if a.release_id is not None} - fetched)
    unmeasured = sum(1 for s in shelves if not s.width_cm and not s.is_showcase)
    # The way to a new layout, in the order of the menu. "open" counts what is left
    # to do in a step; a step with "info" has nothing to count and is never ticked off.
    steps = [
        # With no album at all, taking over the collection is the thing still to do.
        {
            "kind": "discogs",
            "url": url_for("discogs.index"),
            "open": counts["matches"] + to_fetch + (0 if albums else 1),
        },
        # Families and artists come with the albums: without any, these steps are
        # neither to do nor done.
        {"kind": "families", "url": urls["families"], **_countable(counts["families"], albums)},
        {"kind": "artists", "url": urls["artists"], **_countable(counts["artists"], albums)},
        {"kind": "clusters", "url": url_for("clusters.index"), "info": cluster_count},
        # Likewise a collection without a single shelf has its shelves still to enter.
        {
            "kind": "storage",
            "url": urls["overfull"],
            "open": unmeasured + counts["overfull"] + (0 if shelves else 1),
        },
        {"kind": "rules", "url": url_for("rules.index"), "info": len(store.load(LocationRule))},
        {"kind": "proposal", "url": url_for("proposal.index"), "info": int(has_proposal(store))},
    ]
    return render_template(
        "dashboard/index.html",
        album_count=len(sorted_albums),
        placed_count=len(placed),
        single_count=len(albums) - len(sorted_albums),
        artist_count=len(sorted_artists),
        cluster_count=cluster_count,
        steps=steps,
        cabinet_count=len(store.load(Cabinet)),
        shelf_count=len(shelves),
        waiting=[item for item in waiting if item["count"]],
        has_proposal=has_proposal(store),
        last_version=versions[0] if versions else None,
        unsaved=not any(version.is_current for version in versions),
    )
