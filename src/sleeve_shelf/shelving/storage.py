"""Application services for the storage structure: cabinets and their shelves."""

from sleeve_shelf.domain import (
    Album,
    Cabinet,
    Shelf,
    ShelfLayer,
    ShelfType,
    find_by_id,
    move,
    settle_order,
)
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
    """Add a cabinet, at the end of the order, or change one.

    Args:
        store: The store of the collection.
        cabinet_id: The cabinet; None adds one.
        name: Its name.
        location: The room it stands in.
        outside_sorting: Whether a proposal leaves it as it is.

    Returns:
        The cabinet.
    """
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
    """Remove a cabinet; only an empty one, so no shelf is left without a cabinet.

    Args:
        store: The store of the collection.
        cabinet_id: The cabinet.

    Raises:
        StillInUse: It still has shelves.
    """
    cabinets = store.load(Cabinet)
    cabinet = _find(cabinets, cabinet_id)
    if any(shelf.cabinet_id == cabinet_id for shelf in store.load(Shelf)):
        raise StillInUse
    cabinets.remove(cabinet)
    store.save(Cabinet, cabinets)


def move_cabinet(store: JsonStore, cabinet_id: int, step: int) -> None:
    """Move a cabinet a step up (-1) or down (+1) in the order they are walked.

    Args:
        store: The store of the collection.
        cabinet_id: The cabinet.
        step: -1 for up, +1 for down.
    """
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
    width_measured: bool = False,
) -> Shelf:
    """Add a shelf to a cabinet, at the end of it, or change one.

    Args:
        store: The store of the collection.
        cabinet_id: The cabinet.
        shelf_id: The shelf; None adds one.
        name: Its name.
        width_cm: Its width.
        type: Top-loader or front-loader.
        layer: The row it is in: top or bottom.
        reachability_score: The reachability score: a whole number, from the workbook or entered by hand; it does
            not steer the sorting.
        is_showcase: Whether it holds a sample of an artist's albums.
        width_measured: Whether the width was measured.

    Returns:
        The shelf.

    Raises:
        ValueError: A showcase that is not a top-loader, as Shelf says.
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
    # Without a width there is nothing measured.
    shelf.width_measured = width_measured and width_cm is not None
    store.save(Shelf, shelves)
    return shelf


def remove_shelf(store: JsonStore, shelf_id: int) -> None:
    """Remove a shelf; only an empty one, so no album loses its place unnoticed.

    Args:
        store: The store of the collection.
        shelf_id: The shelf.

    Raises:
        StillInUse: It still holds albums.
    """
    shelves = store.load(Shelf)
    shelf = _find(shelves, shelf_id)
    if store.exists(Album) and shelf_id in BrowseQueries(store).shelf_fill():
        raise StillInUse
    shelves.remove(shelf)
    store.save(Shelf, shelves)


def move_shelf(store: JsonStore, shelf_id: int, step: int) -> int:
    """Move a shelf a step up (-1) or down (+1) within its cabinet.

    Args:
        store: The store of the collection.
        shelf_id: The shelf.
        step: -1 for up, +1 for down.

    Returns:
        The cabinet.
    """
    shelves = store.load(Shelf)
    shelf = _find(shelves, shelf_id)
    move([s for s in shelves if s.cabinet_id == shelf.cabinet_id], shelf_id, step)
    store.save(Shelf, shelves)
    return shelf.cabinet_id


def _find[T: (Cabinet, Shelf)](items: list[T], item_id: int) -> T:
    """The cabinet or shelf with this id; LookupError when there is none."""
    item = find_by_id(items, item_id)
    if item is None:
        raise LookupError(item_id)
    return item
