"""Browse/Search: the collection in physical shelf order, and the unplaced albums."""

from flask import Blueprint, redirect, render_template, request, url_for

from sleeve_shelf.config import load_settings
from sleeve_shelf.domain import ProposedPlacement
from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.shelving.moving import carry_out, plan_placing
from sleeve_shelf.shelving.proposal import has_proposal
from sleeve_shelf.web.context import get_store
from sleeve_shelf.web.login import is_owner
from sleeve_shelf.shelving.places import described_spots

blueprint = Blueprint("browse", __name__)


@blueprint.get("/browse")
def browse():
    """Browse/Search: one shelf at a time, or the results of a search."""
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
        shelf_number=index + 1,
        shelf_total=len(shelves),
        previous=shelves[index - 1] if index > 0 else None,
        next=shelves[index + 1] if index < len(shelves) - 1 else None,
    )


@blueprint.get("/unplaced")
def unplaced():
    """The albums that stand on no shelf."""
    store = get_store()
    albums = BrowseQueries(store).unplaced()
    placed = request.args.get("placed", type=int)
    return render_template(
        "browse/unplaced.html",
        albums=albums,
        spots=described_spots(store),
        # The album that was just put at its spot, to say where it went.
        placed_all=request.args.get("placed_all", type=int),
        placed=next((row for row in BrowseQueries(store).everything() if row.album_id == placed), None)
        if placed
        else None,
    )


@blueprint.route("/unplaced/place", methods=["GET", "POST"])
def place_all():
    """Stand the albums waiting for a place at their spots: first what that does, then all at once."""
    store = get_store()
    constants = load_settings(store.data_dir).width_constants
    spots = described_spots(store)
    if request.method == "POST":
        chosen = [album_id for album_id in request.form.getlist("album", type=int) if album_id in spots]
        worked_out = plan_placing(store, chosen, constants) if chosen else None
        if worked_out is not None:
            carry_out(store, worked_out)
        return redirect(url_for("browse.unplaced", placed_all=len(worked_out.moved) if worked_out else 0))
    albums = [row for row in BrowseQueries(store).unplaced() if row.is_lp and row.album_id in spots]
    return render_template(
        "browse/place_all.html",
        albums=albums,
        spots=spots,
        changes=plan_placing(store, list(spots), constants).changes if spots else (),
    )
