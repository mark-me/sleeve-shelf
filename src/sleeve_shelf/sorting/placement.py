"""Physical placement: filling the shelves with the albums in shelf order."""

from dataclasses import dataclass

# Widths are estimates in tenths of a millimetre at best; don't let rounding refuse an album.
TOLERANCE_CM = 0.001


@dataclass(frozen=True, slots=True)
class Spot:
    album_id: int
    shelf_id: int
    position: int


def place(
    albums: list[tuple[int, float, int | None]], shelves: list[tuple[int, int, float]]
) -> tuple[list[Spot], list[int]]:
    """Fill the shelves, honouring the cabinet some albums are bound to by a location rule.

    Albums come as (id, width, mandatory cabinet or None) in shelf order, shelves
    as (id, cabinet, width) in walking order. A cabinet that a rule sends albums
    to holds only those albums; everything else runs over the other cabinets.
    Bound albums that don't fit in their cabinet are left out, not put elsewhere.
    """
    ruled = {cabinet_id for _, _, cabinet_id in albums if cabinet_id is not None}
    spots, left_out = fill_shelves(
        [(album_id, width) for album_id, width, cabinet_id in albums if cabinet_id is None],
        [(shelf_id, width) for shelf_id, cabinet_id, width in shelves if cabinet_id not in ruled],
    )
    for cabinet in sorted(ruled):
        bound_spots, bound_left = fill_shelves(
            [(album_id, width) for album_id, width, cabinet_id in albums if cabinet_id == cabinet],
            [(shelf_id, width) for shelf_id, cabinet_id, width in shelves if cabinet_id == cabinet],
        )
        spots += bound_spots
        left_out += bound_left
    return spots, left_out


def fill_shelves(
    album_widths: list[tuple[int, float]], shelf_widths: list[tuple[int, float]]
) -> tuple[list[Spot], list[int]]:
    """Stand the albums on the shelves, both given in the order they are walked.

    Each shelf is filled until the next album no longer fits; the row then
    continues on the next shelf that has room for it, so an artist can run on
    across shelves. An album no remaining shelf has room for is left out —
    never squeezed in, and never put back on a shelf already passed.

    Returns the spots, and the ids of the albums that did not fit.
    """
    remaining = [width for _, width in shelf_widths]
    filled = [0] * len(shelf_widths)
    spots: list[Spot] = []
    left_out: list[int] = []
    current = 0
    for album_id, width in album_widths:
        target = next(
            (
                index
                for index in range(current, len(shelf_widths))
                if remaining[index] + TOLERANCE_CM >= width
            ),
            None,
        )
        if target is None:
            left_out.append(album_id)
            continue
        current = target
        spots.append(Spot(album_id, shelf_widths[current][0], filled[current]))
        remaining[current] -= width
        filled[current] += 1
    return spots, left_out
