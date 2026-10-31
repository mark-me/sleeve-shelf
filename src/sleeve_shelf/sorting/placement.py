"""Physical placement: filling the shelves with the albums in shelf order."""

from dataclasses import dataclass

# Widths are estimates in tenths of a millimetre at best; don't let rounding refuse an album.
TOLERANCE_CM = 0.001


@dataclass(frozen=True, slots=True)
class Spot:
    """Where an album stands in a filled layout.

    Attributes:
        album_id: The album.
        shelf_id: The shelf.
        position: Its place on the shelf.
    """

    album_id: int
    shelf_id: int
    position: int


def place(
    albums: list[tuple[int, float, int | None]],
    shelves: list[tuple[int, int, float]],
    standing: dict[int, int] | None = None,
) -> tuple[list[Spot], list[int]]:
    """Fill the shelves, honouring the cabinet some albums are bound to by a location rule.

    A cabinet that a rule sends albums to holds only those albums; everything else runs over the
    other cabinets. Bound albums that don't fit in their cabinet are left out, not put elsewhere.

    Args:
        albums: As (id, width, mandatory cabinet or None) in shelf order.
        shelves: As (id, cabinet, width) in walking order.
        standing: The shelf each album stands on now: the boundaries between the shelves are then
            chosen so as many albums as possible stay where they are (see fill_shelves_keeping);
            without, each shelf is filled to the brim.

    Returns:
        The spots, and the ids of the albums left out.
    """

    def fill(album_widths, shelf_widths):
        if standing is None:
            return fill_shelves(album_widths, shelf_widths)
        return fill_shelves_keeping(album_widths, shelf_widths, standing)

    ruled = {cabinet_id for _, _, cabinet_id in albums if cabinet_id is not None}
    spots, left_out = fill(
        [(album_id, width) for album_id, width, cabinet_id in albums if cabinet_id is None],
        [(shelf_id, width) for shelf_id, cabinet_id, width in shelves if cabinet_id not in ruled],
    )
    for cabinet in sorted(ruled):
        bound_spots, bound_left = fill(
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

    Each shelf is filled until the next album no longer fits; the row then continues on the next
    shelf that has room for it, so an artist can run on across shelves. An album no remaining shelf
    has room for is left out — never squeezed in, and never put back on a shelf already passed.

    Args:
        album_widths: The albums as (id, width).
        shelf_widths: The shelves as (id, width).

    Returns:
        The spots, and the ids of the albums that did not fit.
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


def fill_shelves_keeping(
    album_widths: list[tuple[int, float]],
    shelf_widths: list[tuple[int, float]],
    standing: dict[int, int],
) -> tuple[list[Spot], list[int]]:
    """Stand the albums as fill_shelves does, keeping as many as possible on their shelf.

    The order along the shelves is the same, and the same albums are left out; only how far each
    shelf is filled differs. Each shelf takes a run of the albums that follow on from the previous
    one, possibly none, within its width. Among all ways to cut the row like that, the one that
    keeps the most albums on their shelf is chosen; on a tie, the earlier shelves fuller.

    Args:
        album_widths: The albums as (id, width).
        shelf_widths: The shelves as (id, width).
        standing: The shelf each album stands on now.

    Returns:
        The spots, and the ids of the albums that did not fit.
    """
    _greedy, left_out = fill_shelves(album_widths, shelf_widths)
    leaving = set(left_out)
    row = [(album_id, width) for album_id, width in album_widths if album_id not in leaving]
    n, m = len(row), len(shelf_widths)
    prefix = [0.0]
    for _, width in row:
        prefix.append(prefix[-1] + width)
    # stays[j][i]: how many of the first i albums stand on shelf j now.
    stays = []
    for shelf_id, _ in shelf_widths:
        counts = [0]
        for album_id, _ in row:
            counts.append(counts[-1] + (standing.get(album_id) == shelf_id))
        stays.append(counts)

    impossible = -1
    # best[j][i]: the most albums kept in place with the first i albums on the first j shelves.
    best = [[impossible] * (n + 1) for _ in range(m + 1)]
    cut = [[0] * (n + 1) for _ in range(m + 1)]
    best[0][0] = 0
    for j in range(1, m + 1):
        room = shelf_widths[j - 1][1] + TOLERANCE_CM
        kept = stays[j - 1]
        for i in range(n + 1):
            # The shelf takes albums k+1..i; walk k down while they fit.
            k = i
            while k >= 0 and prefix[i] - prefix[k] <= room:
                if best[j - 1][k] != impossible:
                    value = best[j - 1][k] + kept[i] - kept[k]
                    if value > best[j][i]:
                        best[j][i], cut[j][i] = value, k
                k -= 1
    if best[m][n] == impossible:
        # Cannot happen when fill_shelves placed them all; keep its answer to be safe.
        return _greedy, left_out
    spots: list[Spot] = []
    i = n
    for j in range(m, 0, -1):
        k = cut[j][i]
        shelf_id = shelf_widths[j - 1][0]
        spots[:0] = [Spot(row[index][0], shelf_id, index - k) for index in range(k, i)]
        i = k
    return spots, left_out
