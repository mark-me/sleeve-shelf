"""Browse/Search: the collection in physical shelf order, and the unplaced albums."""

from flask import Blueprint, redirect, render_template, request, url_for

from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.web.context import get_store, has_collection

blueprint = Blueprint("browse", __name__)


@blueprint.before_request
def require_collection():
    if not has_collection():
        return redirect(url_for("setup.welcome"))


@blueprint.get("/browse")
def browse():
    queries = BrowseQueries(get_store())
    search_text = request.args.get("q", "").strip()
    if search_text:
        return render_template(
            "browse/results.html", search_text=search_text, albums=queries.search(search_text)
        )

    shelves = queries.shelves()
    if not shelves:
        return render_template("browse/shelf.html", shelves=[], shelf=None, albums=[])
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
        albums=queries.shelf_albums(shelf.shelf_id),
        previous=shelves[index - 1] if index > 0 else None,
        next=shelves[index + 1] if index < len(shelves) - 1 else None,
    )


@blueprint.get("/unplaced")
def unplaced():
    return render_template(
        "browse/unplaced.html", albums=BrowseQueries(get_store()).unplaced()
    )
