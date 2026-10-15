"""Application services for one album or artist: moving it by hand, and the rules that bind it."""

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
    find_by_id,
)
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.versions import keep_restore_point


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
