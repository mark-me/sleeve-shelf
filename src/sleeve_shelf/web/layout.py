"""Layout: the shelves at a glance, adjustable by dragging albums between and within them."""

from itertools import groupby

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from sleeve_shelf.domain import Cabinet, Placement, ProposedPlacement, Shelf, in_order
from sleeve_shelf.persistence import AlbumRow, BrowseQueries
from sleeve_shelf.placing import ShelvesChanged, move_albums, rearrange_shelves
from sleeve_shelf.proposal import has_proposal
from sleeve_shelf.web.context import get_store, shelf_fill

blueprint = Blueprint("layout", __name__, url_prefix="/layout")

# The tray of albums that stand on no shelf is addressed as shelf 0.
TRAY = 0


def _entity(store) -> tuple[type[Placement], str | None]:
    """Which layout is shown and edited: the proposal when asked for and present."""
    if request.values.get("layout") == "proposal" and has_proposal(store):
        return ProposedPlacement, "proposal"
    return Placement, None


def _blocks(rows: list[AlbumRow]) -> list[dict]:
    """Neighbouring albums of one artist, shown and dragged as one block."""
    return [
        {
            "artist": artist,
            "artist_id": artist_id,
            "cluster": albums[0].cluster,
            "era_band": albums[0].era_band,
            "albums": albums,
        }
        for (artist_id, artist), group in groupby(rows, key=lambda row: (row.artist_id, row.artist))
        if (albums := list(group))
    ]


@blueprint.get("/")
def index():
    store = get_store()
    entity, layout = _entity(store)
    queries = BrowseQueries(store, entity)
    fill = queries.shelf_fill()
    shelves = store.load(Shelf)
    all_cabinets = in_order(store.load(Cabinet))
    # One tab per room, in the order the rooms first occur; no tabs while there is only one.
    rooms = list(dict.fromkeys(cabinet.location or "" for cabinet in all_cabinets))
    room = request.args.get("room", rooms[0] if rooms else "")
    if room not in rooms:
        room = rooms[0] if rooms else ""
    cabinets = [
        {
            "cabinet": cabinet,
            "shelves": [
                {
                    "shelf": shelf,
                    **shelf_fill(fill, shelf.id),
                    "blocks": _blocks(queries.shelf_albums(shelf.id)),
                }
                for shelf in in_order([s for s in shelves if s.cabinet_id == cabinet.id])
            ],
        }
        for cabinet in all_cabinets
        if (cabinet.location or "") == room
    ]
    tray = [row for row in queries.unplaced() if row.is_lp]
    # Every shelf of every room, to send a block to without dragging it there.
    destinations = [
        {
            "cabinet": cabinet,
            "room": cabinet.location or "",
            "shelves": [
                {
                    "shelf": shelf,
                    **shelf_fill(fill, shelf.id),
                }
                for shelf in in_order([s for s in shelves if s.cabinet_id == cabinet.id])
            ],
        }
        for cabinet in all_cabinets
    ]
    return render_template(
        "layout/index.html",
        cabinets=cabinets,
        destinations=[entry for entry in destinations if entry["shelves"]],
        tray=_blocks(sorted(tray, key=lambda row: (row.artist.casefold(), row.year or 9999))),
        layout=layout,
        has_proposal=has_proposal(store),
        rooms=rooms if len(rooms) > 1 else [],
        room=room,
    )


@blueprint.get("/go")
def go():
    """Go to cabinet…: to a cabinet, on the tab of its room, or to the albums on no shelf.
    The page itself goes nowhere the list names; the address is made here."""
    store = get_store()
    _, layout = _entity(store)
    to = request.args.get("to", "")
    if to == "tray":
        return redirect(url_for("layout.index", layout=layout, room=request.args.get("room") or None) + "#tray")
    cabinet = next((c for c in store.load(Cabinet) if to.isdigit() and c.id == int(to)), None)
    if cabinet is None:
        return redirect(url_for("layout.index", layout=layout, room=request.args.get("room") or None))
    return redirect(url_for("layout.index", layout=layout, room=cabinet.location or None) + f"#cabinet-{cabinet.id}")


@blueprint.post("/send")
def send():
    """Stand albums at the end of a shelf, in the order given: {albums: [ids], shelf: id}.

    For a move without dragging: the exact spot is then set by dragging within the shelf.
    Shelf 0 is the tray, which takes the albums off their shelf.
    """
    store = get_store()
    entity, _layout = _entity(store)
    payload = request.get_json(silent=True) or {}
    try:
        moving = [int(album_id) for album_id in payload.get("albums") or []]
        target = int(payload.get("shelf"))
    except (TypeError, ValueError):
        return jsonify(error="Albums and the shelf are given by number."), 400
    if not moving:
        return _changed()
    try:
        touched = move_albums(store, moving, None if target == TRAY else target, entity)
    except ShelvesChanged:
        return _changed()
    room = None
    if target != TRAY:
        # The room the shelf is in, for a jump to a shelf that is on another tab.
        cabinet_id = next(shelf.cabinet_id for shelf in store.load(Shelf) if shelf.id == target)
        room = next(c.location for c in store.load(Cabinet) if c.id == cabinet_id) or ""
    return _filled(store, entity, touched, room=room)


@blueprint.post("/move")
def move():
    """Take the new contents of the shelves a drag touched: {shelf id: [album ids in order]}."""
    store = get_store()
    entity, _layout = _entity(store)
    payload = (request.get_json(silent=True) or {}).get("shelves")
    if not isinstance(payload, dict):
        return jsonify(error="No shelves given."), 400
    try:
        contents = {int(shelf_id): [int(a) for a in album_ids] for shelf_id, album_ids in payload.items()}
    except (TypeError, ValueError):
        return jsonify(error="Shelves and albums are given by number."), 400
    tray = contents.pop(TRAY, [])
    try:
        rearrange_shelves(store, contents, tray, entity)
    except ShelvesChanged:
        return _changed()
    return _filled(store, entity, contents)


def _changed():
    return jsonify(error="The shelves have changed; reload the page."), 409


def _filled(store, entity, shelf_ids, **extra):
    """The answer to a move: how full each shelf it touched now is."""
    fill = BrowseQueries(store, entity).shelf_fill()
    return jsonify(
        shelves={str(shelf_id): shelf_fill(fill, shelf_id, digits=1) for shelf_id in shelf_ids},
        **extra,
    )
