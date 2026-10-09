"""What the album and artist pages share: the shelves to move to, and the rules that apply."""

from sleeve_shelf.domain import (
    Album,
    AliasGroup,
    Artist,
    Cabinet,
    Cluster,
    LocationRuleTarget,
    Shelf,
    in_order,
)
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.placing import applicable_rules


def shelf_options(store: JsonStore) -> list[dict]:
    """Every shelf in walking order, to choose from when moving something."""
    shelves = store.load(Shelf)
    return [
        {"id": shelf.id, "cabinet": cabinet.name, "shelf": shelf.name}
        for cabinet in in_order(store.load(Cabinet))
        for shelf in in_order([s for s in shelves if s.cabinet_id == cabinet.id])
    ]


def described_rules(store: JsonStore, artist_id: int, album_id: int | None = None) -> list[dict]:
    """The location rules bearing on an artist or album, named, the deciding one first."""
    rules = applicable_rules(store, artist_id, album_id)
    if not rules:
        return []
    names = {
        LocationRuleTarget.ALBUM: {album.id: album.title for album in store.load(Album)},
        LocationRuleTarget.ARTIST: {artist.id: artist.name for artist in store.load(Artist)},
        LocationRuleTarget.ALIAS_GROUP: {group.id: group.label for group in store.load(AliasGroup)},
        LocationRuleTarget.CLUSTER: {cluster.id: cluster.name for cluster in store.load(Cluster)},
    }
    cabinets = {cabinet.id: cabinet.name for cabinet in store.load(Cabinet)}
    return [
        {
            "kind": rule.target_type.value,
            "target": names[rule.target_type].get(rule.target_id, ""),
            "cabinet": cabinets.get(rule.cabinet_id),
            "note": rule.note,
            "decides": position == 0,
        }
        for position, rule in enumerate(rules)
    ]
