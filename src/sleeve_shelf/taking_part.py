"""What takes part in the sorting: the albums that are sorted, and the shelves that are filled."""

from sleeve_shelf.domain import Album, Cabinet, Placement, Shelf, in_order
from sleeve_shelf.persistence import JsonStore


def takes_part(album: Album, placed_ids: set[int]) -> bool:
    """Whether an album is sorted and placed: LPs are, and whatever already stands on a shelf."""
    if album.id in placed_ids:
        return True
    return album.format_tokens is None or album.format_tokens.is_lp


def kept_shelf_ids(store: JsonStore) -> set[int]:
    """The shelves a proposal leaves exactly as they are.

    A showcase keeps the sample the user put there, and a cabinet kept outside
    the sorting keeps what the user assigned to it. What stands on these
    shelves stays, and takes no part in the row that fills the other shelves.
    """
    outside = {cabinet.id for cabinet in store.load(Cabinet) if cabinet.outside_sorting}
    return {
        shelf.id
        for shelf in store.load(Shelf)
        if shelf.is_showcase or shelf.cabinet_id in outside
    }


def usable_shelves(store: JsonStore) -> tuple[list[Shelf], list[Shelf]]:
    """The shelves a proposal fills, in walking order, and the ones it has to skip.

    Skipped are the shelves that are kept as they are (see kept_shelf_ids), and
    a shelf without a width, which can't be filled.
    """
    kept = kept_shelf_ids(store)
    shelves = store.load(Shelf)
    walked = [
        shelf
        for cabinet in in_order(store.load(Cabinet))
        for shelf in in_order([s for s in shelves if s.cabinet_id == cabinet.id])
    ]
    usable = [shelf for shelf in walked if shelf.width_cm and shelf.id not in kept]
    return usable, [shelf for shelf in walked if shelf not in usable]


def albums_taking_part(store: JsonStore) -> list[Album]:
    """The albums that are sorted and placed, as the shelves stand now (see takes_part)."""
    placed = {p.album_id for p in store.load(Placement)}
    return [album for album in store.load(Album) if takes_part(album, placed)]
