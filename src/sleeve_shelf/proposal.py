"""Application services for the sorting proposal: a layout kept next to the current one."""

from dataclasses import dataclass
from datetime import datetime

from sleeve_shelf.collection import ensure_cluster_order
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
    UnitType,
    WidthConstants,
    in_order,
)
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.sorting.order import OrderedAlbum, Unit, build_units, order_albums
from sleeve_shelf.sorting.placement import place
from sleeve_shelf.versions import save_if_unsaved, save_version


@dataclass(frozen=True, slots=True)
class _Sorted:
    units: list[Unit]
    ordered: list[OrderedAlbum]
    albums: dict[int, Album]


def has_proposal(store: JsonStore) -> bool:
    return store.exists(ProposedPlacement)


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


def _sort(store: JsonStore) -> _Sorted:
    ensure_cluster_order(store)
    placed_ids = {
        p.unit_id for p in store.load(Placement) if p.unit_type is UnitType.ALBUM
    }
    albums = [album for album in store.load(Album) if takes_part(album, placed_ids)]
    # Only confirmed assignments are curated; a proposed cluster is worked out afresh.
    confirmed = [a for a in store.load(ArtistClusterAssignment) if a.confirmed]
    units = build_units(
        store.load(Artist), albums, confirmed, store.load(AliasGroup), store.load(Style)
    )
    ordered = order_albums(units, albums, store.load(Cluster))
    return _Sorted(units, ordered, {album.id: album for album in albums})


def generate_proposal(store: JsonStore, constants: WidthConstants) -> None:
    """Sort the collection and fill the shelves, saved as a proposal next to the current layout."""
    result = _sort(store)
    usable, _skipped = usable_shelves(store)
    cabinet_of = _mandatory_cabinets(store, result)
    # What stands in a showcase, or in a cabinet kept outside the sorting, is the user's
    # own choice: it stays there, and is left out of the row that fills the other shelves.
    kept_ids = kept_shelf_ids(store)
    on_display = [p for p in store.load(Placement) if p.shelf_id in kept_ids]
    displayed = {p.unit_id for p in on_display if p.unit_type is UnitType.ALBUM}
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
    spots, _left_out = place(
        albums, [(shelf.id, shelf.cabinet_id, shelf.width_cm) for shelf in usable]
    )
    store.save(
        ProposedPlacement,
        [
            ProposedPlacement(
                UnitType.ALBUM, spot.album_id, spot.shelf_id, spot.position, PlacementSource.ALGORITHM
            )
            for spot in spots
        ]
        + [
            ProposedPlacement(p.unit_type, p.unit_id, p.shelf_id, p.position, p.source)
            for p in on_display
        ],
    )


def _mandatory_cabinets(store: JsonStore, result: _Sorted) -> dict[int, int]:
    """The cabinet each album is bound to by a location rule, the most specific rule winning:
    the album's own, then its artist's, its family's, its cluster's."""
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
    store.remove(ProposedPlacement)


def accept_proposal(store: JsonStore) -> None:
    """Make the proposal the current layout, with the clusters and era bands it was sorted by."""
    if not has_proposal(store):
        return
    proposed = store.load(ProposedPlacement)
    save_if_unsaved(store, "before proposal")
    result = _sort(store)
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
        [Placement(p.unit_type, p.unit_id, p.shelf_id, p.position, p.source) for p in proposed],
    )
    store.remove(ProposedPlacement)
    save_version(store, "proposal accepted")
