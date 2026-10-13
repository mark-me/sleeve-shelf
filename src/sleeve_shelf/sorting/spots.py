"""A spot for a new purchase: where an album belongs among the albums as they stand."""

from collections import Counter
from dataclasses import dataclass

from sleeve_shelf.sorting.order import OrderedAlbum

# What a spot goes by, from the closest neighbour to the loosest.
ARTIST = "artist"
BAND = "band"
CLUSTER = "cluster"
ORDER = "order"
# Nothing to stand next to: the first album in a cabinet a location rule binds it to.
EMPTY = "empty"


@dataclass(frozen=True, slots=True)
class SuggestedSpot:
    """Where an album would stand: on a shelf, between two albums that stand there now."""

    album_id: int
    shelf_id: int
    # The albums it would stand between; None at either end of the shelf.
    after_album_id: int | None
    before_album_id: int | None
    # Which neighbours the spot was found by: the artist's own albums, the artists of the
    # same era band in its cluster, the cluster, or merely the order of the clusters.
    basis: str


def suggest_spots(
    album_ids: list[int],
    ordered: list[OrderedAlbum],
    unit_of: dict[int, object],
    layout: list[tuple[int, int]],
    allowed_shelves: dict[int, set[int]] | None = None,
    cabinet_of: dict[int, int] | None = None,
) -> dict[int, SuggestedSpot]:
    """For each of the albums: the spot it belongs at in the layout as it stands.

    ordered holds every album that is sorted, the new ones included, in the order a
    sorting would give; layout the albums that stand on a shelf as (album, shelf), in
    the order the shelves are walked. An album goes next to what it belongs with most
    closely: the artist's (or family's) own albums if any stand on a shelf, else the
    artists of its era band in its cluster, else its cluster, else whatever comes before
    it in the order of the clusters. Among those it stands after the last one that
    sorts before it — or before the first one that sorts after it — and never inside
    another artist's row.

    The layout is taken as it is, not as a sorting would have it: what the user moved
    by hand stays the reference. allowed_shelves limits the shelves for some albums (a
    location rule); an album without a cluster, or with nowhere to go, gets no spot.
    """
    rank = {entry.album_id: index for index, entry in enumerate(ordered)}
    entry_of = {entry.album_id: entry for entry in ordered}
    index_in_layout = {album_id: index for index, (album_id, _) in enumerate(layout)}
    shelf_of = dict(layout)
    spots: dict[int, SuggestedSpot] = {}
    for album_id in album_ids:
        entry = entry_of.get(album_id)
        if entry is None or entry.cluster_id is None or album_id in index_in_layout:
            continue
        allowed = (allowed_shelves or {}).get(album_id)
        standing = [
            (other, shelf)
            for other, shelf in layout
            if other in rank and (allowed is None or shelf in allowed)
        ]
        tiers = (
            (ARTIST, lambda o: unit_of.get(o) == unit_of.get(album_id)),
            (BAND, lambda o: (entry_of[o].cluster_id, entry_of[o].band) == (entry.cluster_id, entry.band)),
            (CLUSTER, lambda o: entry_of[o].cluster_id == entry.cluster_id),
            (ORDER, lambda o: True),
        )
        for basis, belongs in tiers:
            near = [other for other, _ in standing if belongs(other)]
            if not near:
                continue
            if cabinet_of and basis != ORDER:
                # Where most of them stand is where they belong; a few kept elsewhere — in
                # a case, with the overflow — are no place to add to.
                homes = Counter(cabinet_of[shelf_of[other]] for other in near)
                home = min(homes, key=lambda cabinet: (-homes[cabinet], cabinet))
                near = [other for other in near if cabinet_of[shelf_of[other]] == home]
            before = [other for other in near if rank[other] < rank[album_id]]
            after = [other for other in near if rank[other] > rank[album_id]]
            if before:
                anchor = max(before, key=rank.get)
                at = index_in_layout[anchor]
                if basis != ARTIST:
                    # Not inside the row of the artist it follows: go on to the end of that row.
                    while _same_row(layout, at, at + 1, unit_of):
                        at += 1
                following = at + 1 if _on_shelf(layout, at + 1, layout[at][1]) else None
                spots[album_id] = SuggestedSpot(
                    album_id,
                    layout[at][1],
                    layout[at][0],
                    layout[following][0] if following is not None else None,
                    basis,
                )
            else:
                anchor = min(after, key=rank.get)
                at = index_in_layout[anchor]
                if basis != ARTIST:
                    while _same_row(layout, at, at - 1, unit_of):
                        at -= 1
                preceding = at - 1 if _on_shelf(layout, at - 1, layout[at][1]) else None
                spots[album_id] = SuggestedSpot(
                    album_id,
                    layout[at][1],
                    layout[preceding][0] if preceding is not None else None,
                    layout[at][0],
                    basis,
                )
            break
    return spots


def _on_shelf(layout: list[tuple[int, int]], index: int, shelf_id: int) -> bool:
    return 0 <= index < len(layout) and layout[index][1] == shelf_id


def _same_row(
    layout: list[tuple[int, int]], index: int, other: int, unit_of: dict[int, object]
) -> bool:
    """Whether the album at other continues the row of the artist at index, on the same shelf."""
    return (
        _on_shelf(layout, other, layout[index][1])
        and unit_of.get(layout[other][0]) is not None
        and unit_of.get(layout[other][0]) == unit_of.get(layout[index][0])
    )
