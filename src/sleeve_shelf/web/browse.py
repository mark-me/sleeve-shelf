"""Browse/Search: the collection in physical shelf order, and the unplaced albums."""

from flask import Blueprint, render_template, request

from sleeve_shelf.domain import ProposedPlacement
from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.shelving.proposal import has_proposal
from sleeve_shelf.web.context import get_store
from sleeve_shelf.web.login import is_owner
from sleeve_shelf.web.places import described_spots

blueprint = Blueprint("browse", __name__)


@blueprint.get("/browse")
def browse():
    store = get_store()
    # The proposal can be browsed like the real shelves, before deciding on it.
    # The proposal can be browsed by the owner only.
    wanted = request.args.get("layout") == "proposal" and is_owner()
    layout = "proposal" if wanted and has_proposal(store) else None
    queries = BrowseQueries(store, ProposedPlacement) if layout else BrowseQueries(store)
    search_text = request.args.get("q", "").strip()
    if search_text and not layout:
        return render_template(
            "browse/results.html", search_text=search_text, albums=queries.search(search_text)
        )

    shelves = queries.shelves()
    if not shelves:
        return render_template("browse/shelf.html", shelves=[], shelf=None, albums=[], layout=layout)
    shelf_id = request.args.get("shelf", type=int)
    index = next((i for i, shelf in enumerate(shelves) if shelf.shelf_id == shelf_id), None)
    if index is None:
        # Start at the first shelf that has something on it.
        index = next((i for i, shelf in enumerate(shelves) if shelf.album_count), 0)
    shelf = shelves[index]
    return render_template(
        "browse/shelf.html",
        shelves=shelves,
        shelf=shelf,
        layout=layout,
        albums=queries.shelf_albums(shelf.shelf_id),
        previous=shelves[index - 1] if index > 0 else None,
        next=shelves[index + 1] if index < len(shelves) - 1 else None,
    )


@blueprint.get("/unplaced")
def unplaced():
    store = get_store()
    albums = BrowseQueries(store).unplaced()
    placed = request.args.get("placed", type=int)
    return render_template(
        "browse/unplaced.html",
        albums=albums,
        spots=described_spots(store),
        # The album that was just put at its spot, to say where it went.
        placed=next((row for row in BrowseQueries(store).everything() if row.album_id == placed), None)
        if placed
        else None,
    )
