"""Application service for a suggested spot: where a new purchase goes on the shelves as they are."""

from dataclasses import dataclass

from sleeve_shelf.domain import (
    Album,
    Cabinet,
    Placement,
    PlacementSource,
    Shelf,
    WidthConstants,
    in_order,
)
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.proposal import mandatory_cabinets, sort_collection
from sleeve_shelf.taking_part import kept_shelf_ids
from sleeve_shelf.sorting.spots import EMPTY, SuggestedSpot, suggest_spots
from sleeve_shelf.versions import keep_restore_point


@dataclass(frozen=True, slots=True)
class Spot:
    """A suggested spot with what is needed to show it."""

    suggestion: SuggestedSpot
    cabinet: str
    shelf: str
    # How much of the shelf's width is left once the album stands there; negative when
    # it then holds more than its width, None when the shelf has no width.
    room_cm: float | None
    # The cabinet a location rule binds the album to, when the spot was found within it.
    by_rule: bool

    @property
    def shelf_id(self) -> int:
        return self.suggestion.shelf_id


def suggested_spots(store: JsonStore, constants: WidthConstants) -> dict[int, Spot]:
    """A spot for every album that is sorted but stands on no shelf yet.

    The shelves are taken as they are. A showcase and a cabinet kept outside the
    sorting are no place to add to; an album a location rule binds to a cabinet gets
    a spot in that cabinet. An album of an artist without a cluster gets none.
    """
    result = sort_collection(store)
    placements = store.load(Placement)
    standing = {p.album_id for p in placements}
    waiting = [album_id for album_id in result.albums if album_id not in standing]
    if not waiting:
        return {}

    kept = kept_shelf_ids(store)
    cabinets = in_order(store.load(Cabinet))
    all_shelves = store.load(Shelf)
    shelves = [
        shelf
        for cabinet in cabinets
        for shelf in in_order([s for s in all_shelves if s.cabinet_id == cabinet.id])
        if shelf.id not in kept
    ]
    walk = {shelf.id: index for index, shelf in enumerate(shelves)}
    layout = [
        (p.album_id, p.shelf_id)
        for p in sorted(
            (p for p in placements if p.shelf_id in walk), key=lambda p: (walk[p.shelf_id], p.position)
        )
    ]
    unit_of = {
        album.id: unit.artist_ids
        for unit in result.units
        for album in result.albums.values()
        if album.artist_id in unit.artist_ids
    }
    bound = mandatory_cabinets(store, result)
    allowed = {
        album_id: {shelf.id for shelf in shelves if shelf.cabinet_id == bound[album_id]}
        for album_id in waiting
        if album_id in bound
    }
    found = suggest_spots(
        waiting,
        result.ordered,
        unit_of,
        layout,
        allowed,
        {shelf.id: shelf.cabinet_id for shelf in shelves},
    )

    clustered = {entry.album_id for entry in result.ordered if entry.cluster_id is not None}
    for album_id, shelf_ids in allowed.items():
        first = next((shelf.id for shelf in shelves if shelf.id in shelf_ids), None)
        if album_id not in found and album_id in clustered and first is not None:
            # Bound to a cabinet nothing stands in yet: it opens that cabinet.
            found[album_id] = SuggestedSpot(album_id, first, None, None, EMPTY)

    all_albums = {album.id: album for album in store.load(Album)}

    def width(album_id: int) -> float:
        album = all_albums.get(album_id)
        return (album.width_cm if album else None) or constants.base_per_disc

    filled: dict[int, float] = {}
    for album_id, shelf_id in layout:
        filled[shelf_id] = filled.get(shelf_id, 0.0) + width(album_id)
    cabinet_names = {cabinet.id: cabinet.name for cabinet in cabinets}
    by_id = {shelf.id: shelf for shelf in shelves}
    spots = {}
    for album_id, suggestion in found.items():
        shelf = by_id[suggestion.shelf_id]
        room = (
            shelf.width_cm - filled.get(shelf.id, 0.0) - width(album_id)
            if shelf.width_cm
            else None
        )
        spots[album_id] = Spot(
            suggestion, cabinet_names[shelf.cabinet_id], shelf.name, room, album_id in bound
        )
    return spots


def place_at_spot(store: JsonStore, album_id: int, constants: WidthConstants) -> Spot | None:
    """Stand the album at its suggested spot, between the albums named there.

    The spot is worked out afresh, so it is the one for the shelves as they are now.
    This changes the shelves, so a version to go back to is kept first. Returns the
    spot, or None when there is none to place the album at.
    """
    spot = suggested_spots(store, constants).get(album_id)
    if spot is None:
        return None
    keep_restore_point(store)
    placements = store.load(Placement)
    on_shelf = sorted(
        (p for p in placements if p.shelf_id == spot.shelf_id), key=lambda p: p.position
    )
    after = spot.suggestion.after_album_id
    index = next((i + 1 for i, p in enumerate(on_shelf) if p.album_id == after), 0)
    on_shelf.insert(index, Placement(album_id, spot.shelf_id, index, PlacementSource.MANUAL))
    for position, placement in enumerate(on_shelf):
        placement.position = position
    store.save(Placement, [p for p in placements if p.shelf_id != spot.shelf_id] + on_shelf)
    return spot
