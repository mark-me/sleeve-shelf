"""What is waiting for the user: the counts behind the Dashboard list and the menu."""

from pathlib import Path

from sleeve_shelf.alias_groups import family_suggestions
from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    Cabinet,
    Cluster,
    EraBand,
    MatchProposal,
    Placement,
    Shelf,
)
from sleeve_shelf.persistence import BrowseQueries, JsonStore
from sleeve_shelf.proposal import takes_part

# The shelf fill is a query over all of these; it fails while one is missing.
_LAYOUT_ENTITIES = (Album, Artist, ArtistClusterAssignment, Cabinet, Cluster, EraBand, Placement, Shelf)


def waiting_counts(store: JsonStore) -> dict[str, int]:
    """Per kind of open point, how many there are; kinds without any are included as 0."""
    albums = store.load(Album)
    placed = {p.album_id for p in store.load(Placement)}
    sorted_albums = [album for album in albums if takes_part(album, placed)]
    sorted_artists = {album.artist_id for album in sorted_albums}
    confirmed = {a.artist_id for a in store.load(ArtistClusterAssignment) if a.confirmed}
    start_years = {artist.id for artist in store.load(Artist) if artist.start_year}
    overfull = 0
    if all(store.exists(entity) for entity in _LAYOUT_ENTITIES):
        fill = BrowseQueries(store).shelf_fill()
        overfull = sum(
            1
            for shelf in store.load(Shelf)
            if shelf.width_cm and fill.get(shelf.id, (0, 0.0))[1] > shelf.width_cm
        )
    return {
        "matches": len(store.load(MatchProposal)),
        "families": len(family_suggestions(store)),
        "artists": sum(1 for a in sorted_artists if a not in confirmed or a not in start_years),
        "widths": sum(1 for album in sorted_albums if not album.width_confirmed),
        "unlinked": sum(1 for album in sorted_albums if album.release_id is None),
        "gone": sum(1 for a in albums if a.left_discogs and not a.kept_after_discogs),
        "overfull": overfull,
        "unplaced": sum(1 for album in sorted_albums if album.id not in placed),
    }


# The menu is on every page, so its counts are only worked out again when a data file changed.
_menu_cache: dict[Path, tuple[tuple, dict[str, int]]] = {}


def menu_counts(store: JsonStore) -> dict[str, int]:
    """The counts shown behind menu items, by the blueprint or endpoint they belong to."""
    signature = tuple(
        sorted((path.name, path.stat().st_mtime_ns) for path in store.data_dir.glob("*.json"))
    )
    cached = _menu_cache.get(store.data_dir)
    if cached is None or cached[0] != signature:
        cached = (signature, _menu_counts(store))
        _menu_cache[store.data_dir] = cached
    return cached[1]


def _menu_counts(store: JsonStore) -> dict[str, int]:
    counts = waiting_counts(store)
    return {
        "unplaced": counts["unplaced"],
        "artists": counts["artists"],
        "families": counts["families"],
        "storage": counts["overfull"],
        "discogs": counts["matches"] + counts["gone"],
    }
