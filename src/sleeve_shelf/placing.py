"""Application services for one album or artist: moving it by hand, and the rules that bind it.
Also a whole cluster or family, moved to a shelf at once."""

from dataclasses import dataclass

from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    LocationRule,
    LocationRuleTarget,
    Placement,
    PlacementSource,
    ProposedPlacement,
    Shelf,
    WidthConstants,
    find_by_id,
)
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.proposal import sort_collection
from sleeve_shelf.sorting.placement import Spot, fill_shelves
from sleeve_shelf.taking_part import kept_shelf_ids, usable_shelves
from sleeve_shelf.versions import keep_restore_point, save_if_unsaved


class ShelvesChanged(ValueError):
    """A move names albums or shelves that are not as the page showed them: nothing was moved."""


def move_albums(
    store: JsonStore,
    album_ids: list[int],
    shelf_id: int | None,
    entity: type[Placement] | type[ProposedPlacement] = Placement,
) -> set[int]:
    """Stand albums at the end of a shelf, in the order given; None takes them off their shelf.

    Works on the shelves as they are, or on the proposal (entity). A change to the shelves as
    they are keeps a version to go back to first. Returns the shelves whose contents changed.
    """
    if (
        len(album_ids) != len(set(album_ids))
        or not set(album_ids) <= {album.id for album in store.load(Album)}
        or (shelf_id is not None and shelf_id not in {shelf.id for shelf in store.load(Shelf)})
    ):
        raise ShelvesChanged
    moving = set(album_ids)
    placements = store.load(entity)
    touched = {p.shelf_id for p in placements if p.album_id in moving} | {shelf_id} - {None}
    kept = [p for p in placements if p.album_id not in moving]
    if shelf_id is not None:
        following = max((p.position for p in kept if p.shelf_id == shelf_id), default=-1) + 1
        kept += [
            entity(album_id, shelf_id, following + offset, PlacementSource.MANUAL)
            for offset, album_id in enumerate(album_ids)
        ]
    _save(store, entity, kept)
    return touched


def rearrange_shelves(
    store: JsonStore,
    contents: dict[int, list[int]],
    off_shelf: list[int] = (),
    entity: type[Placement] | type[ProposedPlacement] = Placement,
) -> None:
    """Give shelves new contents, as a drag left them: per shelf its albums in order.

    Albums in off_shelf are taken off their shelf. Nothing may silently drop off a shelf:
    every album that stood on one of these shelves has to be named again, somewhere.
    """
    named = [album_id for ids in contents.values() for album_id in ids] + list(off_shelf)
    placements = store.load(entity)
    before = {p.album_id for p in placements if p.shelf_id in contents}
    if (
        len(named) != len(set(named))
        or not set(named) <= {album.id for album in store.load(Album)}
        or not set(contents) <= {shelf.id for shelf in store.load(Shelf)}
        or not before <= set(named)
    ):
        raise ShelvesChanged
    kept = [p for p in placements if p.shelf_id not in contents and p.album_id not in named]
    moved = [
        entity(album_id, shelf_id, position, PlacementSource.MANUAL)
        for shelf_id, ids in contents.items()
        for position, album_id in enumerate(ids)
    ]
    _save(store, entity, kept + moved)


@dataclass(frozen=True, slots=True)
class PlacedRun:
    """What moving a cluster or family did."""

    # Its albums that now stand from the chosen shelf on.
    moved: int
    # The shelves filled anew: the chosen one and those after it in its cabinet.
    shelf_ids: tuple[int, ...]
    # How much more the last of them holds than its width, when not everything fitted.
    over_cm: float = 0.0


def _sorted_on_shelves(store: JsonStore) -> list[tuple[int, int | None, int | None]]:
    """The albums that stand on a shelf a proposal fills, as (album, cluster, family), in the
    order a proposal sorts them: by cluster, era band, artist (a family together) and year.

    The cluster is the one a proposal sorts the album under. What stands in a showcase, or
    in a cabinet kept outside the sorting, is left where it is, as by a proposal.
    """
    kept = kept_shelf_ids(store)
    shelf_of = {p.album_id: p.shelf_id for p in store.load(Placement)}
    family_of = {artist.id: artist.alias_group_id for artist in store.load(Artist)}
    result = sort_collection(store)
    return [
        (entry.album_id, entry.cluster_id, family_of.get(result.albums[entry.album_id].artist_id))
        for entry in result.ordered
        if entry.album_id in shelf_of and shelf_of[entry.album_id] not in kept
    ]


def cluster_albums_on_shelves(store: JsonStore, cluster_id: int) -> list[int]:
    """The albums of a cluster that stand on a shelf a proposal fills, in sorting order."""
    return [album for album, cluster, _family in _sorted_on_shelves(store) if cluster == cluster_id]


def family_albums_on_shelves(store: JsonStore) -> dict[int, list[int]]:
    """Per family, its albums that stand on a shelf a proposal fills, in sorting order."""
    families: dict[int, list[int]] = {}
    for album, _cluster, family in _sorted_on_shelves(store):
        if family is not None:
            families.setdefault(family, []).append(album)
    return families


def place_cluster(
    store: JsonStore, cluster_id: int, shelf_id: int, constants: WidthConstants
) -> PlacedRun:
    """Stand the albums of a cluster together from the start of a shelf on (see _place_run)."""
    return _place_run(store, cluster_albums_on_shelves(store, cluster_id), shelf_id, constants)


def place_family(
    store: JsonStore, group_id: int, shelf_id: int, constants: WidthConstants
) -> PlacedRun:
    """Stand the albums of a family together from the start of a shelf on (see _place_run)."""
    return _place_run(store, family_albums_on_shelves(store).get(group_id, []), shelf_id, constants)


def _place_run(
    store: JsonStore, moving: list[int], shelf_id: int, constants: WidthConstants
) -> PlacedRun:
    """Stand these albums, in this order, from the start of a shelf on, running on over the
    shelves after it in the same cabinet; what stood there moves up behind them.

    The shelves before the chosen one, and the other cabinets, keep their albums except
    these, which leave their places. Nothing drops off: what no longer fits stays at the end
    of the last shelf of the cabinet, which is then reported as holding too much. The layout
    as it was is kept as a version first.
    """
    usable, _skipped = usable_shelves(store)
    start = next((shelf for shelf in usable if shelf.id == shelf_id), None)
    if start is None:
        raise ShelvesChanged
    in_cabinet = [shelf for shelf in usable if shelf.cabinet_id == start.cabinet_id]
    chain = in_cabinet[in_cabinet.index(start):]
    if not moving:
        return PlacedRun(0, ())
    placements = store.load(Placement)
    order = {shelf.id: index for index, shelf in enumerate(chain)}
    leaving = set(moving)
    staying = [
        p.album_id
        for p in sorted(
            (p for p in placements if p.shelf_id in order and p.album_id not in leaving),
            key=lambda p: (order[p.shelf_id], p.position),
        )
    ]
    albums = {album.id: album for album in store.load(Album)}
    widths = {
        album_id: albums[album_id].width_cm or constants.base_per_disc
        for album_id in moving + staying
    }
    spots, left_out = fill_shelves(
        [(album_id, widths[album_id]) for album_id in moving + staying],
        [(shelf.id, shelf.width_cm) for shelf in chain],
    )
    last = chain[-1]
    after = max((spot.position for spot in spots if spot.shelf_id == last.id), default=-1) + 1
    spots += [Spot(album_id, last.id, after + offset) for offset, album_id in enumerate(left_out)]
    on_last = sum(widths[spot.album_id] for spot in spots if spot.shelf_id == last.id)

    save_if_unsaved(store, "before moving albums together")
    store.save(
        Placement,
        [p for p in placements if p.shelf_id not in order and p.album_id not in leaving]
        + [Placement(spot.album_id, spot.shelf_id, spot.position, PlacementSource.MANUAL) for spot in spots],
    )
    return PlacedRun(
        len(moving), tuple(shelf.id for shelf in chain), max(0.0, on_last - last.width_cm) if left_out else 0.0
    )


def _save(store: JsonStore, entity: type, placements: list) -> None:
    # A change by hand to the shelves as they are can always be undone; the proposal is
    # itself the thing kept aside.
    if entity is Placement:
        keep_restore_point(store)
    store.save(entity, placements)


def applicable_rules(
    store: JsonStore, artist_id: int, album_id: int | None = None
) -> list[LocationRule]:
    """The location rules that bear on an artist, or on one of its albums, the deciding one first.

    The most specific rule decides: the album's own, then the artist's, its family's, its cluster's.
    """
    artist = find_by_id(store.load(Artist), artist_id)
    cluster_id = next(
        (a.cluster_id for a in store.load(ArtistClusterAssignment) if a.artist_id == artist_id),
        None,
    )
    targets = [
        (LocationRuleTarget.ALBUM, album_id),
        (LocationRuleTarget.ARTIST, artist_id),
        (LocationRuleTarget.ALIAS_GROUP, artist.alias_group_id if artist else None),
        (LocationRuleTarget.CLUSTER, cluster_id),
    ]
    rules = {(rule.target_type, rule.target_id): rule for rule in store.load(LocationRule)}
    return [rules[target] for target in targets if target[1] is not None and target in rules]


def set_rule(
    store: JsonStore, target_type: LocationRuleTarget, target_id: int, cabinet_id: int, note: str = ""
) -> LocationRule:
    """Bind a cluster, family, artist or album to a cabinet. A target has one rule: a new
    rule for it replaces the old."""
    rules = [
        rule
        for rule in store.load(LocationRule)
        if (rule.target_type, rule.target_id) != (target_type, target_id)
    ]
    rule = LocationRule(store.next_id(LocationRule, rules), target_type, target_id, cabinet_id, note)
    store.save(LocationRule, [*rules, rule])
    return rule


def remove_rule(store: JsonStore, rule_id: int) -> None:
    store.save(LocationRule, [rule for rule in store.load(LocationRule) if rule.id != rule_id])
