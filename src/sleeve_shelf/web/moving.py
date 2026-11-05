"""The Move screen: an album, artist, family or cluster to a shelf, next to an album, or to where it belongs.

What it would do is shown before anything moves.
"""

from flask import Blueprint, abort, redirect, render_template, request, url_for

from sleeve_shelf.config import load_settings
from sleeve_shelf.domain import Album
from sleeve_shelf.library.artists import set_cluster
from sleeve_shelf.shelving.moving import (
    NEXT_TO,
    OFF_SHELF,
    How,
    Kind,
    carry_out,
    cluster_offer,
    find,
    plan,
    selection,
)
from sleeve_shelf.shelving.placing import ShelvesChanged
from sleeve_shelf.web.context import get_store
from sleeve_shelf.shelving.places import albums_to_stand_next_to, shelf_options

blueprint = Blueprint("moving", __name__, url_prefix="/move")


def _chosen(store, values):
    """What the request names to move, how and where; None for each part it leaves open."""
    kind = values.get("kind")
    item_id = values.get("id", type=int)
    chosen = selection(store, Kind(kind), item_id) if kind in Kind and item_id is not None else None
    how = How(values["how"]) if values.get("how") in How else None
    shelf_id = values.get("shelf", type=int)
    next_to = values.get("next_to", type=int)
    return chosen, how, shelf_id, next_to


def _complete(how, shelf_id, next_to) -> bool:
    """Whether the request says enough to work out a plan."""
    if how is None:
        return False
    if how in NEXT_TO:
        return next_to is not None
    return how is How.BELONGS or shelf_id is not None


@blueprint.get("/")
def index():
    """The Move screen: what, how and where, and the plan to look at before it is carried out."""
    store = get_store()
    chosen, how, shelf_id, next_to = _chosen(store, request.args)
    if request.args.get("kind") and chosen is None:
        abort(404)
    text = request.args.get("q", "").strip()
    found = []
    if chosen is None and text:
        found = [
            {"kind": kind, "id": item_id, "name": name, "albums": albums}
            for kind, item_id, name, albums in find(store, text)
        ]
    near = request.args.get("near", "").strip()
    nearby = albums_to_stand_next_to(store, near, frozenset(chosen.album_ids)) if chosen and near else []
    planned = offer = None
    if chosen is not None and _complete(how, shelf_id, next_to):
        try:
            planned = plan(store, chosen, how, shelf_id, load_settings(store.data_dir).width_constants, next_to)
        except ShelvesChanged:
            abort(400)
        offer = cluster_offer(store, chosen, planned.next_to)
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
        next_to_name=_next_to_name(store, planned),
        cluster_offer=offer,
        near=near,
        nearby=nearby,
        titles=titles,
        done=request.args.get("done", type=int),
        done_cabinet=request.args.get("cabinet", type=int),
    )


def _next_to_name(store, planned):
    """The album a plan stands the albums next to, as artist and title."""
    if planned is None or planned.next_to is None:
        return ""
    chosen = selection(store, Kind.ALBUM, planned.next_to)
    return chosen.name if chosen else ""


@blueprint.post("/")
def move():
    """Carry out the move as it is worked out now, on the shelves as they stand."""
    store = get_store()
    chosen, how, shelf_id, next_to = _chosen(store, request.form)
    if chosen is None or not _complete(how, shelf_id, next_to):
        abort(400)
    try:
        planned = plan(store, chosen, how, shelf_id, load_settings(store.data_dir).width_constants, next_to)
    except ShelvesChanged:
        abort(400)
    # Worked out before moving: afterwards the album stands where the cluster asks for already.
    offer = cluster_offer(store, chosen, planned.next_to) if request.form.get("confirm_cluster") else None
    carry_out(store, planned)
    if offer is not None:
        set_cluster(store, offer["artist_id"], offer["cluster_id"])
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
