"""What the album and artist pages share: the shelves to choose from, and the rules that apply."""

from sleeve_shelf.config import load_settings
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
from sleeve_shelf.spots import suggested_spots


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


def described_spots(store: JsonStore) -> dict[int, dict]:
    """Per album that waits for a place: its suggested spot, with the albums it would stand between."""
    spots = suggested_spots(store, load_settings(store.data_dir).width_constants)
    if not spots:
        return {}
    albums = {album.id: album for album in store.load(Album)}
    artists = {artist.id: artist.name for artist in store.load(Artist)}

    def named(album_id: int | None, shelf_id: int) -> dict | None:
        album = albums.get(album_id)
        if album is None:
            return None
        return {
            "id": album.id,
            "artist": artists.get(album.artist_id, ""),
            "title": album.title,
            "shelf_id": shelf_id,
        }

    return {
        album_id: {
            "shelf_id": spot.shelf_id,
            "cabinet": spot.cabinet,
            "shelf": spot.shelf,
            "after": named(spot.suggestion.after_album_id, spot.shelf_id),
            "before": named(spot.suggestion.before_album_id, spot.shelf_id),
            "basis": spot.suggestion.basis,
            "room_cm": spot.room_cm,
            "width_measured": spot.width_measured,
            "by_rule": spot.by_rule,
        }
        for album_id, spot in spots.items()
    }

