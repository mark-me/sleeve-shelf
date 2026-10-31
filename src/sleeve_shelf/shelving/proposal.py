"""Application services for the sorting proposal: a layout kept next to the current one."""

from dataclasses import dataclass
from math import ceil

from sleeve_shelf.config import load_settings
from sleeve_shelf.library.alias_groups import cluster_hints, family_suggestions
from sleeve_shelf.library.collection import ensure_cluster_order
from sleeve_shelf.domain import (
    Album,
    AliasGroup,
    Artist,
    ArtistClusterAssignment,
    Cabinet,
    Cluster,
    EraBand,
    EraBandSource,
    LocationRule,
    LocationRuleTarget,
    Placement,
    PlacementSource,
    ProposedPlacement,
    Shelf,
    Style,
    WidthConstants,
    in_order,
)
from sleeve_shelf.persistence import BrowseQueries, JsonStore
from sleeve_shelf.sorting.order import OrderedAlbum, Unit, build_units, order_albums
from sleeve_shelf.sorting.placement import place
from sleeve_shelf.library.taking_part import albums_taking_part, kept_shelf_ids, takes_part, usable_shelves
from sleeve_shelf.library.versions import save_if_unsaved, save_version


@dataclass(frozen=True, slots=True)
class Sorted:
    """The collection as a proposal sorts it.

    Attributes:
        units: The artists and families sorted, as units on the shelf.
        ordered: The albums in their order.
        albums: The albums by id.
    """

    units: list[Unit]
    ordered: list[OrderedAlbum]
    albums: dict[int, Album]


def has_proposal(store: JsonStore) -> bool:
    """Whether a sorting proposal is waiting next to the layout.

    Args:
        store: The store of the collection.

    Returns:
        True when there is one.
    """
    return store.exists(ProposedPlacement)


def sort_collection(store: JsonStore, unplaced: set[int] | frozenset[int] = frozenset()) -> Sorted:
    """The albums in the order a proposal stands them in.

    Args:
        store: The store of the collection.
        unplaced: Albums sorted as if they stood nowhere yet — those being moved, whose place now is
            not the owner's choice.

    Returns:
        The sorted collection.
    """
    ensure_cluster_order(store)
    placed_ids = {
        p.album_id for p in store.load(Placement)
    }
    albums = [album for album in store.load(Album) if takes_part(album, placed_ids)]
    # Only confirmed assignments are curated; a proposed cluster is worked out afresh.
    confirmed = [a for a in store.load(ArtistClusterAssignment) if a.confirmed]
    # A loose connection is an indication for the user, not something to sort by.
    connected = {
        artist_id: hint.cluster_id
        for artist_id, hint in cluster_hints(store).items()
        if hint.decisive
    }
    units = build_units(
        store.load(Artist), albums, confirmed, store.load(AliasGroup), store.load(Style), connected
    )
    standing = {album_id: index for album_id, index in _standing(store).items() if album_id not in unplaced}
    ordered = order_albums(units, albums, store.load(Cluster), standing)
    return Sorted(units, ordered, {album.id: album for album in albums})


def _standing(store: JsonStore) -> dict[int, int]:
    """Each album's place along the walked shelves as they stand now.

    A showcase and a cabinet kept outside the sorting are left out: what stands there says nothing
    about the order of the shelves that are sorted.
    """
    kept = kept_shelf_ids(store)
    shelves = store.load(Shelf)
    walk = {
        shelf.id: index
        for index, shelf in enumerate(
            shelf
            for cabinet in in_order(store.load(Cabinet))
            for shelf in in_order([s for s in shelves if s.cabinet_id == cabinet.id])
        )
    }
    standing = sorted(
        (p for p in store.load(Placement) if p.shelf_id in walk and p.shelf_id not in kept),
        key=lambda p: (walk[p.shelf_id], p.position),
    )
    return {p.album_id: index for index, p in enumerate(standing)}


def generate_proposal(store: JsonStore, constants: WidthConstants, room_percent: int = 0) -> None:
    """Sort the collection and fill the shelves, saved as a proposal next to the current layout.

    The boundaries between the shelves are chosen so as many albums as possible stay on the shelf
    they stand on now: the order is the same as filling each shelf to the brim, but far fewer
    records have to be moved to carry it out (see sorting.placement.fill_shelves_keeping).

    Args:
        store: The store of the collection.
        constants: The width figures.
        room_percent: Each shelf is filled to at most (100 - room_percent)% of its width.
    """
    result = sort_collection(store)
    usable, _skipped = usable_shelves(store)
    cabinet_of = mandatory_cabinets(store, result)
    # What stands in a showcase, or in a cabinet kept outside the sorting, is the user's
    # own choice: it stays there, and is left out of the row that fills the other shelves.
    kept_ids = kept_shelf_ids(store)
    on_display = [p for p in store.load(Placement) if p.shelf_id in kept_ids]
    displayed = {p.album_id for p in on_display}
    # An album whose format is unknown is taken to be a single LP.
    albums = [
        (
            o.album_id,
            result.albums[o.album_id].width_cm or constants.base_per_disc,
            cabinet_of.get(o.album_id),
        )
        for o in result.ordered
        if o.album_id not in displayed
    ]
    share = (100 - room_percent) / 100
    standing = {p.album_id: p.shelf_id for p in store.load(Placement)}
    spots, _left_out = place(
        albums,
        [(shelf.id, shelf.cabinet_id, shelf.width_cm * share) for shelf in usable],
        standing,
    )
    store.save(
        ProposedPlacement,
        [
            ProposedPlacement(
                spot.album_id, spot.shelf_id, spot.position, PlacementSource.ALGORITHM
            )
            for spot in spots
        ]
        + [
            ProposedPlacement(p.album_id, p.shelf_id, p.position, p.source)
            for p in on_display
        ],
    )


def mandatory_cabinets(store: JsonStore, result: Sorted) -> dict[int, int]:
    """The cabinet each album is bound to by a location rule.

    The most specific rule wins: the album's own, then its artist's, its family's, its cluster's.

    Args:
        store: The store of the collection.
        result: The sorted collection.

    Returns:
        The cabinet by album id.
    """
    rules: dict[LocationRuleTarget, dict[int, int]] = {target: {} for target in LocationRuleTarget}
    for rule in store.load(LocationRule):
        rules[rule.target_type][rule.target_id] = rule.cabinet_id
    family_of = {artist.id: artist.alias_group_id for artist in store.load(Artist)}
    cluster_of = {o.album_id: o.cluster_id for o in result.ordered}

    bound = {}
    for album_id, album in result.albums.items():
        for target, target_id in (
            (LocationRuleTarget.ALBUM, album_id),
            (LocationRuleTarget.ARTIST, album.artist_id),
            (LocationRuleTarget.ALIAS_GROUP, family_of.get(album.artist_id)),
            (LocationRuleTarget.CLUSTER, cluster_of.get(album_id)),
        ):
            if target_id in rules[target]:
                bound[album_id] = rules[target][target_id]
                break
    return bound


def discard_proposal(store: JsonStore) -> None:
    """Throw the waiting proposal away; the layout stays as it is.

    Args:
        store: The store of the collection.
    """
    store.remove(ProposedPlacement)


def accept_proposal(store: JsonStore) -> None:
    """Make the proposal the current layout, with the clusters and era bands it was sorted by.

    Args:
        store: The store of the collection.
    """
    if not has_proposal(store):
        return
    proposed = store.load(ProposedPlacement)
    save_if_unsaved(store, "before proposal")
    result = sort_collection(store)
    unit_of = {artist_id: unit for unit in result.units for artist_id in unit.artist_ids}

    # A cluster the engine proposed for an artist is recorded as such: unconfirmed.
    assignments = [a for a in store.load(ArtistClusterAssignment) if a.confirmed]
    confirmed_ids = {a.artist_id for a in assignments}
    for artist_id, unit in unit_of.items():
        if artist_id not in confirmed_ids and unit.cluster_id is not None:
            assignments.append(ArtistClusterAssignment(artist_id, unit.cluster_id, confirmed=False))

    # The era bands follow the sorting: one band per artist that takes part.
    albums = store.load(Album)
    era_bands: list[EraBand] = []
    band_ids: dict[int, int] = {}
    for album in albums:
        unit = unit_of.get(album.artist_id) if album.id in result.albums else None
        if unit is None:
            album.era_band_id = None
            continue
        if album.artist_id not in band_ids:
            band_ids[album.artist_id] = len(era_bands) + 1
            era_bands.append(
                EraBand(band_ids[album.artist_id], album.artist_id, unit.band, 0, EraBandSource.ALGORITHM)
            )
        album.era_band_id = band_ids[album.artist_id]

    store.save(ArtistClusterAssignment, assignments)
    store.save(EraBand, era_bands)
    store.save(Album, albums)
    store.save(
        Placement,
        [Placement(p.album_id, p.shelf_id, p.position, p.source) for p in proposed],
    )
    store.remove(ProposedPlacement)
    save_version(store, "proposal accepted")


def proposal_overview(store: JsonStore) -> dict:
    """What the Sorting proposal screen shows: what takes part, and a proposal next to the layout.

    Args:
        store: The store of the collection.

    Returns:
        What the screen's template uses, by name.
    """
    usable, skipped = usable_shelves(store)
    kept = kept_shelf_ids(store)
    outside = {cabinet.id for cabinet in store.load(Cabinet) if cabinet.outside_sorting}
    cabinet_names = {cabinet.id: cabinet.name for cabinet in store.load(Cabinet)}
    current = {
        p.album_id: p.shelf_id for p in store.load(Placement)
    }
    albums = albums_taking_part(store)
    context = {
        # What stands on a kept shelf stays there, and is not among the albums to place.
        "taking_part": sum(1 for album in albums if current.get(album.id) not in kept),
        "usable_count": len(usable),
        "skipped": [
            {"cabinet": cabinet_names[s.cabinet_id], "shelf": s, "outside": s.cabinet_id in outside}
            for s in skipped
        ],
        "suggestion_count": len(family_suggestions(store)),
        "has_proposal": has_proposal(store),
    }
    if not context["has_proposal"]:
        return context

    proposed = {p.album_id: p.shelf_id for p in store.load(ProposedPlacement)}
    artist_names = {artist.id: artist.name for artist in store.load(Artist)}
    now_fill = BrowseQueries(store).shelf_fill()
    new_fill = BrowseQueries(store, ProposedPlacement).shelf_fill()
    shelves = usable + skipped
    cabinets = [
        {
            "name": cabinet.name,
            "shelves": [
                {
                    "shelf": shelf,
                    "skipped": shelf in skipped,
                    "kept": shelf.id in kept,
                    "outside": shelf.cabinet_id in outside,
                    "now": now_fill.get(shelf.id, (0, 0.0)),
                    "new": new_fill.get(shelf.id, (0, 0.0)),
                }
                for shelf in in_order([s for s in shelves if s.cabinet_id == cabinet.id])
            ],
        }
        for cabinet in in_order(store.load(Cabinet))
    ]
    left_out = sorted(
        (
            {"album_id": album.id, "artist": artist_names[album.artist_id], "title": album.title,
             "was_placed": album.id in current}
            for album in albums
            if album.id not in proposed
        ),
        key=lambda row: (row["artist"].casefold(), row["title"].casefold()),
    )
    moved_count = sum(1 for album_id, shelf_id in proposed.items() if current.get(album_id) != shelf_id)
    settings = load_settings(store.data_dir)
    return {
        **context,
        "cabinets": cabinets,
        "placed_count": len(proposed),
        "left_out": left_out,
        "moved_count": moved_count,
        "staying_count": sum(1 for album_id, shelf_id in proposed.items() if current.get(album_id) == shelf_id),
        # What carrying it out takes: every album that moves passes over the table once.
        "table_records": settings.table_records,
        "rounds": ceil(moved_count / settings.table_records),
        "room_percent": settings.shelf_room_percent,
    }
