"""The Move screen: an album, artist, family or cluster to a shelf or to where it belongs.

What it would do is shown before anything moves.
"""

from flask import Blueprint, abort, redirect, render_template, request, url_for

from sleeve_shelf.config import load_settings
from sleeve_shelf.domain import Album
from sleeve_shelf.shelving.moving import OFF_SHELF, How, Kind, carry_out, find, plan, selection
from sleeve_shelf.shelving.placing import ShelvesChanged
from sleeve_shelf.web.context import get_store
from sleeve_shelf.shelving.places import shelf_options

blueprint = Blueprint("moving", __name__, url_prefix="/move")


def _chosen(store, values):
    """What the request names to move, how and where; None for each part it leaves open."""
    kind = values.get("kind")
    item_id = values.get("id", type=int)
    chosen = selection(store, Kind(kind), item_id) if kind in Kind and item_id is not None else None
    how = How(values["how"]) if values.get("how") in How else None
    shelf_id = values.get("shelf", type=int)
    return chosen, how, shelf_id


@blueprint.get("/")
def index():
    """The Move screen: what, how and where, and the plan to look at before it is carried out."""
    store = get_store()
    chosen, how, shelf_id = _chosen(store, request.args)
    if request.args.get("kind") and chosen is None:
        abort(404)
    text = request.args.get("q", "").strip()
    found = []
    if chosen is None and text:
        found = [
            {"kind": kind, "id": item_id, "name": name, "albums": albums}
            for kind, item_id, name, albums in find(store, text)
        ]
    planned = None
    if chosen is not None and how is not None and (how is How.BELONGS or shelf_id is not None):
        try:
            planned = plan(store, chosen, how, shelf_id, load_settings(store.data_dir).width_constants)
        except ShelvesChanged:
            abort(400)
    titles = {}
    if planned is not None and planned.without_spot:
        albums = {album.id: album.title for album in store.load(Album)}
        titles = {album_id: albums.get(album_id, "") for album_id in planned.without_spot}
    return render_template(
        "moving/index.html",
        search_text=text,
        found=found,
        chosen=chosen,
        how=how,
        shelf_id=shelf_id,
        shelves=shelf_options(store),
        off_shelf=OFF_SHELF,
        plan=planned,
        titles=titles,
        done=request.args.get("done", type=int),
        done_cabinet=request.args.get("cabinet", type=int),
    )


@blueprint.post("/")
def move():
    """Carry out the move as it is worked out now, on the shelves as they stand."""
    store = get_store()
    chosen, how, shelf_id = _chosen(store, request.form)
    if chosen is None or how is None or (how is not How.BELONGS and shelf_id is None):
        abort(400)
    try:
        planned = plan(store, chosen, how, shelf_id, load_settings(store.data_dir).width_constants)
    except ShelvesChanged:
        abort(400)
    carry_out(store, planned)
    # Where it went: the first shelf it stands on now, in walking order.
    landed = next((change for change in planned.changes if change.after > change.before), None)
    return redirect(
        url_for(
            "moving.index",
            kind=chosen.kind.value,
            id=chosen.id,
            done=len(planned.moved),
            cabinet=landed.cabinet_id if landed else None,
        )
    )
