"""Application services for one album or artist: moving it by hand, and the rules that bind it."""

from sleeve_shelf.domain import (
    Artist,
    ArtistClusterAssignment,
    LocationRule,
    LocationRuleTarget,
    Placement,
    PlacementSource,
)
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.versions import keep_restore_point


def move_albums(store: JsonStore, album_ids: list[int], shelf_id: int | None) -> None:
    """Stand albums at the end of a shelf, in the order given; None takes them off their shelf.

    This changes the shelves as they are, so a version to go back to is kept first.
    """
    keep_restore_point(store)
    moving = set(album_ids)
    placements = [
        p
        for p in store.load(Placement)
        if p.album_id not in moving
    ]
    if shelf_id is not None:
        following = max((p.position for p in placements if p.shelf_id == shelf_id), default=-1) + 1
        placements += [
            Placement(album_id, shelf_id, following + offset, PlacementSource.MANUAL)
            for offset, album_id in enumerate(album_ids)
        ]
    store.save(Placement, placements)


def applicable_rules(
    store: JsonStore, artist_id: int, album_id: int | None = None
) -> list[LocationRule]:
    """The location rules that bear on an artist, or on one of its albums, the deciding one first.

    The most specific rule decides: the album's own, then the artist's, its family's, its cluster's.
    """
    artist = next((a for a in store.load(Artist) if a.id == artist_id), None)
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
