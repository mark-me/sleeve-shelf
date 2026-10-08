"""Layout: the shelves at a glance, adjustable by dragging albums between and within them."""

from itertools import groupby

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from sleeve_shelf.domain import (
    Album,
    Cabinet,
    Placement,
    PlacementSource,
    ProposedPlacement,
    Shelf,
    UnitType,
    in_order,
)
from sleeve_shelf.persistence import AlbumRow, BrowseQueries
from sleeve_shelf.proposal import has_proposal
from sleeve_shelf.versions import keep_restore_point
from sleeve_shelf.web.context import get_store, has_collection

blueprint = Blueprint("layout", __name__, url_prefix="/layout")

# The tray of albums that stand on no shelf is addressed as shelf 0.
TRAY = 0


@blueprint.before_request
def require_collection():
    if not has_collection():
        return redirect(url_for("setup.welcome"))


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
                    "albums": fill.get(shelf.id, (0, 0.0))[0],
                    "filled_cm": fill.get(shelf.id, (0, 0.0))[1],
                    "blocks": _blocks(queries.shelf_albums(shelf.id)),
                }
                for shelf in in_order([s for s in shelves if s.cabinet_id == cabinet.id])
            ],
        }
        for cabinet in all_cabinets
        if (cabinet.location or "") == room
    ]
    tray = [row for row in queries.unplaced() if row.is_lp]
    return render_template(
        "layout/index.html",
        cabinets=cabinets,
        tray=_blocks(sorted(tray, key=lambda row: (row.artist.casefold(), row.year or 9999))),
        layout=layout,
        has_proposal=has_proposal(store),
        rooms=rooms if len(rooms) > 1 else [],
        room=room,
    )


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

    placements = store.load(entity)
    album_ids = {album.id for album in store.load(Album)}
    shelf_ids = {shelf.id for shelf in store.load(Shelf)}
    named = [album_id for ids in contents.values() for album_id in ids]
    before = {p.unit_id for p in placements if p.shelf_id in contents}
    if (
        not set(named) <= album_ids
        or not set(contents) - {TRAY} <= shelf_ids
        or len(named) != len(set(named))
        # Nothing may silently drop off a shelf: what was there has to be accounted for.
        or not before <= set(named)
    ):
        return jsonify(error="The shelves have changed; reload the page."), 409

    kept = [
        p for p in placements
        if p.shelf_id not in contents and p.unit_id not in named
    ]
    moved = [
        entity(UnitType.ALBUM, album_id, shelf_id, position, PlacementSource.MANUAL)
        for shelf_id, ids in contents.items()
        if shelf_id != TRAY
        for position, album_id in enumerate(ids)
    ]
    if entity is Placement:
        keep_restore_point(store)
    store.save(entity, kept + moved)
    fill = BrowseQueries(store, entity).shelf_fill()
    return jsonify(
        shelves={
            str(shelf_id): {
                "albums": fill.get(shelf_id, (0, 0.0))[0],
                "filled_cm": round(fill.get(shelf_id, (0, 0.0))[1], 1),
            }
            for shelf_id in contents
            if shelf_id != TRAY
        }
    )
