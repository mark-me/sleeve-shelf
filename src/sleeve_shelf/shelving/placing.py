"""Application services for one album or artist: moving it by hand, and the rules that bind it."""

import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager, nullcontext

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
from sleeve_shelf.library.versions import keep_restore_point


class ShelvesChanged(ValueError):
    """A move names albums or shelves that are not as the page showed them: nothing was moved."""


class ProposalGone(ShelvesChanged):
    """The proposal a change was meant for was accepted or discarded meanwhile: nothing changed."""


# One change to the proposal at a time: making, accepting or discarding it, and adjusting it.
# Without it a move worked out on the proposal could be saved after another request accepted or
# discarded the proposal, and bring it back next to shelves that already changed. The app runs as
# one process with several threads (waitress), so a lock in memory is enough. Re-entrant, as
# accepting a proposal holds it while calling what holds it too.
_PROPOSAL = threading.RLock()


@contextmanager
def proposal_changes() -> Iterator[None]:
    """Hold the proposal for one change to it: a second change waits until the first is done.

    Returns:
        A context in which the proposal is held, until the block ends.
    """
    with _PROPOSAL:
        yield


@contextmanager
def proposal_edit(store: JsonStore) -> Iterator[None]:
    """Hold the proposal for adjusting it, refusing when there is none any more.

    Args:
        store: The store of the collection.

    Returns:
        A context in which the proposal is held, until the block ends.

    Raises:
        ProposalGone: The proposal was accepted or discarded meanwhile.
    """
    with _PROPOSAL:
        if not store.exists(ProposedPlacement):
            raise ProposalGone
        yield


def _held(store: JsonStore, entity: type):
    """Holding the proposal while it is adjusted; the shelves as they are need nothing."""
    return proposal_edit(store) if entity is ProposedPlacement else nullcontext()


def move_albums(
    store: JsonStore,
    album_ids: list[int],
    shelf_id: int | None,
    entity: type[Placement] | type[ProposedPlacement] = Placement,
) -> set[int]:
    """Stand albums at the end of a shelf, in the order given.

    A change to the shelves as they are keeps a version to go back to first.

    Args:
        store: The store of the collection.
        album_ids: The albums.
        shelf_id: The shelf; None takes them off their shelf.
        entity: The layout to work on: the shelves as they are, or the proposal.

    Returns:
        The shelves whose contents changed.

    Raises:
        ShelvesChanged: An album is named twice or is not there, or the shelf is not there.
    """
    with _held(store, entity):
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


def contents_before(
    store: JsonStore,
    shelf_ids: Iterable[int],
    album_ids: Iterable[int],
    entity: type[Placement] | type[ProposedPlacement] = Placement,
) -> tuple[dict[int, list[int]], list[int]]:
    """What a move is about to change, to put back with rearrange_shelves when it is undone.

    Args:
        store: The store of the collection.
        shelf_ids: The shelves the move names.
        album_ids: The albums it moves.
        entity: The layout to work on: the shelves as they are, or the proposal.

    Returns:
        Per shelf concerned its albums in order, and the albums among those moved that stand on no
        shelf now.
    """
    moving = set(album_ids)
    placements = sorted(store.load(entity), key=lambda p: p.position)
    standing = {p.album_id for p in placements}
    concerned = set(shelf_ids) | {p.shelf_id for p in placements if p.album_id in moving}
    contents: dict[int, list[int]] = {shelf_id: [] for shelf_id in concerned}
    for placement in placements:
        if placement.shelf_id in concerned:
            contents[placement.shelf_id].append(placement.album_id)
    return contents, sorted(moving - standing)


def rearrange_shelves(
    store: JsonStore,
    contents: dict[int, list[int]],
    off_shelf: list[int] = (),
    entity: type[Placement] | type[ProposedPlacement] = Placement,
) -> None:
    """Give shelves new contents, as a drag left them.

    Nothing may silently drop off a shelf: every album that stood on one of these shelves has to be
    named again, somewhere.

    Args:
        store: The store of the collection.
        contents: Per shelf its albums in order.
        off_shelf: Albums taken off their shelf.
        entity: The layout to work on: the shelves as they are, or the proposal.

    Raises:
        ShelvesChanged: The page did not show the shelves as they are, or an album would drop off.
    """
    with _held(store, entity):
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

    Args:
        store: The store of the collection.
        artist_id: The artist.
        album_id: The album, when it is about one.

    Returns:
        The rules.
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
    """Bind a cluster, family, artist or album to a cabinet.

    A target has one rule: a new rule for it replaces the old.

    Args:
        store: The store of the collection.
        target_type: What it binds.
        target_id: The id of that.
        cabinet_id: The cabinet.
        note: Why.

    Returns:
        The rule.
    """
    rules = [
        rule
        for rule in store.load(LocationRule)
        if (rule.target_type, rule.target_id) != (target_type, target_id)
    ]
    rule = LocationRule(store.next_id(LocationRule, rules), target_type, target_id, cabinet_id, note)
    store.save(LocationRule, [*rules, rule])
    return rule


def remove_rule(store: JsonStore, rule_id: int) -> None:
    """Remove a location rule.

    Args:
        store: The store of the collection.
        rule_id: The rule.
    """
    store.save(LocationRule, [rule for rule in store.load(LocationRule) if rule.id != rule_id])
