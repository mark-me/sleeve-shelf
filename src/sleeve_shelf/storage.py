"""Application services for the storage structure: cabinets and their shelves."""

from sleeve_shelf.domain import Album, Cabinet, Shelf, ShelfLayer, ShelfType, move, settle_order
from sleeve_shelf.persistence import BrowseQueries, JsonStore


class StillInUse(Exception):
    """A cabinet that still has shelves, or a shelf that still holds albums: it stays."""


def save_cabinet(
    store: JsonStore,
    cabinet_id: int | None,
    name: str,
    location: str | None = None,
    outside_sorting: bool = False,
) -> Cabinet:
    """Add a cabinet (cabinet_id None), at the end of the order, or change one."""
    cabinets = store.load(Cabinet)
    if cabinet_id is None:
        cabinet = Cabinet(store.next_id(Cabinet, cabinets), name)
        cabinets.append(cabinet)
        settle_order(cabinets, [])
    else:
        cabinet = _find(cabinets, cabinet_id)
    cabinet.name = name
    cabinet.location = location or None
    cabinet.outside_sorting = outside_sorting
    store.save(Cabinet, cabinets)
    return cabinet


def remove_cabinet(store: JsonStore, cabinet_id: int) -> None:
    """Remove a cabinet; only an empty one, so no shelf is left without a cabinet."""
    cabinets = store.load(Cabinet)
    cabinet = _find(cabinets, cabinet_id)
    if any(shelf.cabinet_id == cabinet_id for shelf in store.load(Shelf)):
        raise StillInUse
    cabinets.remove(cabinet)
    store.save(Cabinet, cabinets)


def move_cabinet(store: JsonStore, cabinet_id: int, step: int) -> None:
    """Move a cabinet a step up (-1) or down (+1) in the order they are walked."""
    cabinets = store.load(Cabinet)
    _find(cabinets, cabinet_id)
    move(cabinets, cabinet_id, step)
    store.save(Cabinet, cabinets)


def save_shelf(
    store: JsonStore,
    cabinet_id: int,
    shelf_id: int | None,
    name: str,
    width_cm: float | None = None,
    type: ShelfType | None = None,
    layer: ShelfLayer | None = None,
    reachability_score: int | None = None,
    is_showcase: bool = False,
) -> Shelf:
    """Add a shelf to a cabinet (shelf_id None), at the end of it, or change one.

    Only a top-loader can be a showcase; anything else raises ValueError, as Shelf does.
    """
    if is_showcase and type is not ShelfType.TOP_LOADER:
        raise ValueError("Only a top-loader shelf can be a showcase")
    cabinet = _find(store.load(Cabinet), cabinet_id)
    shelves = store.load(Shelf)
    if shelf_id is None:
        shelf = Shelf(store.next_id(Shelf, shelves), cabinet.id, name)
        shelves.append(shelf)
        settle_order([cabinet], shelves)
    else:
        shelf = _find(shelves, shelf_id)
    shelf.name = name
    shelf.width_cm = width_cm
    shelf.type = type
    shelf.layer = layer
    shelf.reachability_score = reachability_score
    shelf.is_showcase = is_showcase
    store.save(Shelf, shelves)
    return shelf


def remove_shelf(store: JsonStore, shelf_id: int) -> None:
    """Remove a shelf; only an empty one, so no album loses its place unnoticed."""
    shelves = store.load(Shelf)
    shelf = _find(shelves, shelf_id)
    if store.exists(Album) and shelf_id in BrowseQueries(store).shelf_fill():
        raise StillInUse
    shelves.remove(shelf)
    store.save(Shelf, shelves)


def move_shelf(store: JsonStore, shelf_id: int, step: int) -> int:
    """Move a shelf a step up (-1) or down (+1) within its cabinet; returns the cabinet."""
    shelves = store.load(Shelf)
    shelf = _find(shelves, shelf_id)
    move([s for s in shelves if s.cabinet_id == shelf.cabinet_id], shelf_id, step)
    store.save(Shelf, shelves)
    return shelf.cabinet_id


def _find[T: (Cabinet, Shelf)](items: list[T], item_id: int) -> T:
    """The cabinet or shelf with this id; LookupError when there is none."""
    item = next((item for item in items if item.id == item_id), None)
    if item is None:
        raise LookupError(item_id)
    return item
