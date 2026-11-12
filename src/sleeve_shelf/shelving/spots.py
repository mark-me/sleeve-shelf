"""Application service for a suggested spot: where a new purchase goes on the shelves as they are."""

from dataclasses import dataclass

from sleeve_shelf.domain import (
    Style,
    Album,
    ArtistClusterAssignment,
    Cabinet,
    Cluster,
    Placement,
    PlacementSource,
    Shelf,
    WidthConstants,
    in_order,
)
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.shelving.proposal import Sorted, mandatory_cabinets, sort_collection
from sleeve_shelf.sorting.order import clusters_by_styles
from sleeve_shelf.sorting.spots import EMPTY, SuggestedSpot, suggest_spots
from sleeve_shelf.library.taking_part import kept_shelf_ids
from sleeve_shelf.library.artists import set_cluster
from sleeve_shelf.library.versions import keep_restore_point


@dataclass(frozen=True, slots=True)
class Spot:
    """A suggested spot with what is needed to show it.

    Attributes:
        suggestion: Where it is.
        cabinet: The name of the cabinet.
        shelf: The name of the shelf.
        room_cm: How much of the shelf's width is left once the album stands there; negative when it
            then holds more than its width, None when the shelf has no width.
        width_measured: Whether that width was measured, or is an estimate.
        by_rule: The cabinet a location rule binds the album to, when the spot was found within it.
        cluster_id: The cluster the album is sorted under.
        cluster_proposed: Whether that cluster is only proposed: its artist has none confirmed.
    """

    suggestion: SuggestedSpot
    cabinet: str
    shelf: str
    room_cm: float | None
    width_measured: bool
    by_rule: bool
    cluster_id: int | None = None
    cluster_proposed: bool = False

    @property
    def shelf_id(self) -> int:
        """The shelf of the spot."""
        return self.suggestion.shelf_id


def belonging(
    store: JsonStore, album_ids: list[int], placements: list[Placement], result: Sorted | None = None
) -> dict[int, SuggestedSpot]:
    """Where each of these albums belongs: next to the albums it belongs with, as they stand.

    A showcase and a cabinet kept outside the sorting are no place to go to; an album a location
    rule binds to a cabinet goes within it. An album of an artist without a cluster, or one that is
    not sorted, gets no spot (see sorting.spots).

    Args:
        store: The store of the collection.
        album_ids: The albums.
        placements: The layout to place them in, which must not hold them.
        result: The sorted collection, when the caller has it already.

    Returns:
        The spots by album id.
    """
    result = result or sort_collection(store)
    kept = kept_shelf_ids(store)
    shelves = _walked_shelves(store, kept)
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
        for album_id in album_ids
        if album_id in bound
    }
    found = suggest_spots(
        album_ids,
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
    return found


def _walked_shelves(store: JsonStore, kept: set[int]) -> list[Shelf]:
    """The shelves something can be added to, in walking order."""
    all_shelves = store.load(Shelf)
    return [
        shelf
        for cabinet in in_order(store.load(Cabinet))
        for shelf in in_order([s for s in all_shelves if s.cabinet_id == cabinet.id])
        if shelf.id not in kept
    ]


def suggested_spots(
    store: JsonStore, constants: WidthConstants, assumed: dict[int, int] | None = None
) -> dict[int, Spot]:
    """A spot for every album that is sorted but stands on no shelf yet.

    The shelves are taken as they are (see belonging).

    Args:
        store: The store of the collection.
        constants: The width figures.
        assumed: Clusters by artist id to sort by as if they were confirmed.

    Returns:
        The spots by album id.
    """
    result = sort_collection(store, assumed=assumed)
    placements = store.load(Placement)
    standing = {p.album_id for p in placements}
    waiting = [album_id for album_id in result.albums if album_id not in standing]
    if not waiting:
        return {}
    found = belonging(store, waiting, placements, result)
    bound = mandatory_cabinets(store, result)
    cabinets = in_order(store.load(Cabinet))
    shelves = _walked_shelves(store, kept_shelf_ids(store))
    walk = {shelf.id for shelf in shelves}
    layout = [(p.album_id, p.shelf_id) for p in placements if p.shelf_id in walk]

    all_albums = {album.id: album for album in store.load(Album)}

    def width(album_id: int) -> float:
        album = all_albums.get(album_id)
        return (album.width_cm if album else None) or constants.base_per_disc

    unit_of = {artist_id: unit for unit in result.units for artist_id in unit.artist_ids}
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
        unit = unit_of.get(all_albums[album_id].artist_id) if album_id in all_albums else None
        spots[album_id] = Spot(
            suggestion,
            cabinet_names[shelf.cabinet_id],
            shelf.name,
            room,
            width_measured=shelf.width_measured,
            by_rule=album_id in bound,
            cluster_id=unit.cluster_id if unit else None,
            cluster_proposed=bool(unit and unit.cluster_is_proposed),
        )
    return spots


def place_at_spot(
    store: JsonStore, album_id: int, constants: WidthConstants, assumed: dict[int, int] | None = None
) -> Spot | None:
    """Stand the album at its suggested spot, between the albums named there.

    The spot is worked out afresh, so it is the one for the shelves as they are now. This changes
    the shelves, so a version to go back to is kept first.

    Args:
        store: The store of the collection.
        album_id: The album.
        constants: The width figures.
        assumed: Clusters by artist id to find the spot as if they were confirmed: another of
            the spots offered.

    Returns:
        The spot, or None when there is none to place the album at.
    """
    spot = suggested_spots(store, constants, assumed).get(album_id)
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


# How many other spots an album whose artist has no confirmed cluster is offered.
OTHER_SPOTS = 2


def other_spots(store: JsonStore, album_id: int, constants: WidthConstants) -> list[Spot]:
    """Spots in the other clusters the styles point to, for an album whose cluster is only proposed.

    The suggested spot goes by the cluster the styles point to most; these go by the next ones, as
    if the artist were confirmed in that cluster.

    Args:
        store: The store of the collection.
        album_id: The album.
        constants: The width figures.

    Returns:
        At most OTHER_SPOTS spots, each in another cluster; none when the cluster is confirmed.
    """
    artist_ids, clusters = _other_clusters(store, album_id)
    found = []
    for cluster_id in clusters:
        spot = suggested_spots(store, constants, dict.fromkeys(artist_ids, cluster_id)).get(album_id)
        if spot is not None:
            found.append(spot)
        if len(found) == OTHER_SPOTS:
            break
    return found


def _other_clusters(store: JsonStore, album_id: int) -> tuple[tuple[int, ...], list[int]]:
    """The artists sorted with the album, and the other clusters their styles point to, most first.

    No clusters when the album's cluster is confirmed, or comes from its connections.
    """
    result = sort_collection(store)
    album = result.albums.get(album_id)
    unit = next((u for u in result.units if album and album.artist_id in u.artist_ids), None)
    if unit is None or not unit.cluster_is_proposed:
        return (), []
    styles = {style.id: style for style in store.load(Style)}
    unit_albums = [a for a in result.albums.values() if a.artist_id in unit.artist_ids]
    return tuple(unit.artist_ids), [c for c in clusters_by_styles(unit_albums, styles) if c != unit.cluster_id]


def place_in_cluster(
    store: JsonStore, album_id: int, cluster_id: int, constants: WidthConstants, confirm: bool
) -> Spot | None:
    """Stand the album at the spot offered in another cluster, and put its artist there if asked.

    Args:
        store: The store of the collection.
        album_id: The album.
        cluster_id: The cluster of one of the other spots offered (other_spots).
        constants: The width figures.
        confirm: Whether the album's artist is put in that cluster as confirmed, so that a later
            proposal keeps it there.

    Returns:
        The spot, or None when that cluster is not one of the other spots offered as the shelves
        stand now.
    """
    # The same spots as the album's page offers, worked out anew: a cluster further down the
    # styles, or one offered on a page opened before the shelves changed, is refused.
    if cluster_id not in {spot.cluster_id for spot in other_spots(store, album_id, constants)}:
        return None
    artist_ids, _ = _other_clusters(store, album_id)
    album = next((a for a in store.load(Album) if a.id == album_id), None)
    # Standing it there and confirming its cluster stand or fall together.
    with store.together(Placement, ArtistClusterAssignment, Cluster):
        spot = place_at_spot(store, album_id, constants, dict.fromkeys(artist_ids, cluster_id))
        if spot is not None and confirm and album is not None:
            set_cluster(store, album.artist_id, cluster_id)
    return spot
