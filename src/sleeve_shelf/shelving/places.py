"""What the album and artist pages share: the shelves to choose from, and the rules that apply."""

from sleeve_shelf.config import load_settings
from sleeve_shelf.domain import (
    Album,
    AliasGroup,
    Artist,
    Cabinet,
    Cluster,
    LocationRuleTarget,
    Placement,
    Shelf,
    in_order,
    sort_name,
)
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.shelving.placing import applicable_rules
from sleeve_shelf.shelving.spots import other_spots, suggested_spots


def shelf_options(store: JsonStore) -> list[dict]:
    """Every shelf in walking order, to choose from when moving something.

    Args:
        store: The store of the collection.

    Returns:
        One entry per shelf, with its cabinet's name.
    """
    shelves = store.load(Shelf)
    return [
        {"id": shelf.id, "cabinet": cabinet.name, "shelf": shelf.name}
        for cabinet in in_order(store.load(Cabinet))
        for shelf in in_order([s for s in shelves if s.cabinet_id == cabinet.id])
    ]


def albums_to_stand_next_to(
    store: JsonStore,
    text: str,
    leaving: frozenset[int] = frozenset(),
    limit: int = 12,
    layout: type[Placement] = Placement,
) -> list[dict]:
    """Albums on a shelf whose artist and title hold every word of the text, in walking order.

    Args:
        store: The store of the collection.
        text: What was typed: an artist, a title, or both.
        leaving: Albums that are moved themselves, and so are left out.
        limit: How many at most.
        layout: Where they stand: the shelves (Placement) or the proposal (ProposedPlacement).

    Returns:
        One entry per album, with its artist, title, cabinet and shelf.
    """
    words = sort_name(text).split()
    if not words:
        return []
    artists = {artist.id: artist.name for artist in store.load(Artist)}
    albums = {album.id: album for album in store.load(Album)}
    shelves = {option["id"]: (index, option) for index, option in enumerate(shelf_options(store))}
    found = []
    for placement in store.load(layout):
        album = albums.get(placement.album_id)
        if album is None or album.id in leaving or placement.shelf_id not in shelves:
            continue
        artist = artists.get(album.artist_id, "")
        name = sort_name(f"{artist} {album.title}")
        if all(word in name for word in words):
            index, option = shelves[placement.shelf_id]
            found.append(((index, placement.position), {
                "id": album.id, "artist": artist, "title": album.title,
                "cabinet": option["cabinet"], "shelf": option["shelf"],
            }))
    return [entry for _, entry in sorted(found, key=lambda pair: pair[0])[:limit]]


def described_rules(store: JsonStore, artist_id: int, album_id: int | None = None) -> list[dict]:
    """The location rules bearing on an artist or album, named, the deciding one first.

    Args:
        store: The store of the collection.
        artist_id: The artist.
        album_id: The album, when it is about one.

    Returns:
        One entry per rule, for a template.
    """
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
    """Per album that waits for a place: its suggested spot, with the albums it would stand between.

    Args:
        store: The store of the collection.

    Returns:
        The spots by album id, for a template.
    """
    # For the pages to show only, so it can be kept; placing an album works its spot out afresh.
    return store.remembered("described spots", lambda: _described_spots(store))


def _described_spots(store: JsonStore) -> dict[int, dict]:
    spots = suggested_spots(store, load_settings(store.data_dir).width_constants)
    if not spots:
        return {}
    describe = _describer(store)
    return {album_id: describe(spot) for album_id, spot in spots.items()}


def described_other_spots(store: JsonStore, album_id: int) -> list[dict]:
    """The spots in the other clusters the styles point to, for an album whose cluster is proposed.

    Args:
        store: The store of the collection.
        album_id: The album.

    Returns:
        One entry per spot, for a template; none when the artist's cluster is confirmed.
    """
    spots = other_spots(store, album_id, load_settings(store.data_dir).width_constants)
    if not spots:
        return []
    describe = _describer(store)
    return [describe(spot) for spot in spots]


def _describer(store: JsonStore):
    """What a template shows of a spot: names rather than ids."""
    albums = {album.id: album for album in store.load(Album)}
    artists = {artist.id: artist.name for artist in store.load(Artist)}
    clusters = {cluster.id: cluster.name for cluster in store.load(Cluster)}

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

    def describe(spot) -> dict:
        album = albums.get(spot.suggestion.album_id)
        return {
            "shelf_id": spot.shelf_id,
            "cabinet": spot.cabinet,
            "shelf": spot.shelf,
            "after": named(spot.suggestion.after_album_id, spot.shelf_id),
            "before": named(spot.suggestion.before_album_id, spot.shelf_id),
            "basis": spot.suggestion.basis,
            "room_cm": spot.room_cm,
            "width_measured": spot.width_measured,
            "by_rule": spot.by_rule,
            "cluster_id": spot.cluster_id,
            "cluster": clusters.get(spot.cluster_id),
            "cluster_proposed": spot.cluster_proposed,
            "artist_id": album.artist_id if album else None,
            "artist": artists.get(album.artist_id, "") if album else "",
        }

    return describe
