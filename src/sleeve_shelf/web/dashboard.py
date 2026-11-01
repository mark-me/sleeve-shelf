"""Dashboard: the collection at a glance, and what is waiting for a decision."""

from flask import Blueprint, render_template, request, url_for

from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.web.context import get_store
from sleeve_shelf.shelving.places import described_spots
from sleeve_shelf.shelving.overview import collection_figures
from sleeve_shelf.shelving.waiting import waiting_counts

blueprint = Blueprint("dashboard", __name__, url_prefix="/dashboard")

# How many albums to place are shown on the Dashboard itself; the rest is one click away.
TO_PLACE_SHOWN = 3


def _countable(open_count: int, has_albums: bool) -> dict:
    return {"open": open_count} if has_albums else {"later": True}


@blueprint.get("/")
def index():
    """The Dashboard: the collection at a glance, and what waits for a decision."""
    store = get_store()
    figures = collection_figures(store)
    counts = waiting_counts(store)
    urls = {
        "matches": url_for("discogs.index") + "#matches",
        "families": url_for("families.index"),
        "artists": url_for("artists.index", show="attention"),
        "shifts": url_for("artists.index", show="attention"),
        "rule_suggestions": url_for("rules.index") + "#suggested",
        "widths": url_for("albums.widths"),
        "unlinked": url_for("discogs.index"),
        "gone": url_for("discogs.index") + "#gone",
        "overfull": url_for("storage.index"),
        "unplaced": url_for("browse.unplaced"),
    }
    waiting = [{"count": counts[kind], "kind": kind, "url": url} for kind, url in urls.items()]
    # The way to a new layout, in the order of the menu. "open" counts what is left
    # to do in a step; a step with "info" has nothing to count and is never ticked off.
    steps = [
        # With no album at all, taking over the collection is the thing still to do.
        {
            "kind": "discogs",
            "url": url_for("discogs.index"),
            "open": counts["matches"] + figures["to_fetch"] + (0 if figures["has_albums"] else 1),
        },
        # Families and artists come with the albums: without any, these steps are
        # neither to do nor done.
        {"kind": "families", "url": urls["families"], **_countable(counts["families"], figures["has_albums"])},
        {"kind": "artists", "url": urls["artists"], **_countable(counts["artists_in_all"], figures["has_albums"])},
        {"kind": "clusters", "url": url_for("clusters.index"), "info": figures["cluster_count"]},
        # Likewise a collection without a single shelf has its shelves still to enter.
        {
            "kind": "storage",
            "url": urls["overfull"],
            "open": figures["unmeasured"] + counts["overfull"] + (0 if figures["shelf_count"] else 1),
        },
        {"kind": "rules", "url": url_for("rules.index"), "info": figures["rule_count"]},
        {"kind": "proposal", "url": url_for("proposal.index"), "info": int(figures["has_proposal"])},
    ]
    # The LPs that wait for a place, each with the spot suggested for it, until they stand there.
    queries = BrowseQueries(store)
    to_place = [row for row in queries.unplaced() if row.is_lp] if counts["unplaced"] else []
    spots = described_spots(store) if to_place else {}
    just_placed = request.args.get("placed", type=int)
    return render_template(
        "dashboard/index.html",
        to_place=to_place[:TO_PLACE_SHOWN],
        to_place_count=len(to_place),
        spots=spots,
        placed=next((row for row in queries.everything() if row.album_id == just_placed), None)
        if just_placed
        else None,
        **figures,
        steps=steps,
        waiting=[item for item in waiting if item["count"]],
    )
