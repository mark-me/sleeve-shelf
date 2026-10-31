"""What is waiting for the user: the counts behind the Dashboard list and the menu."""

from pathlib import Path

from sleeve_shelf.library.alias_groups import family_suggestions
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
from sleeve_shelf.shelving.rule_suggestions import rule_suggestions
from sleeve_shelf.shelving.shifts import cluster_shifts
from sleeve_shelf.library.taking_part import albums_taking_part

# The shelf fill is a query over all of these; it fails while one is missing.
_LAYOUT_ENTITIES = (Album, Artist, ArtistClusterAssignment, Cabinet, Cluster, EraBand, Placement, Shelf)


# The counts are on every page, in the menu, and take a while to work out (family suggestions
# compare every artist with every other): they are worked out again only when a data file or
# the settings changed.
_cache: dict[Path, tuple[tuple, dict[str, int]]] = {}


def waiting_counts(store: JsonStore) -> dict[str, int]:
    """Per kind of open point, how many there are; kinds without any are included as 0."""
    files = [*store.data_dir.glob("*.json"), store.data_dir / "config.yaml"]
    signature = tuple(
        sorted((path.name, path.stat().st_mtime_ns) for path in files if path.exists())
    )
    cached = _cache.get(store.data_dir)
    if cached is None or cached[0] != signature:
        cached = (signature, _waiting_counts(store))
        _cache[store.data_dir] = cached
    # A copy, so a caller changing it does not change what is kept.
    return dict(cached[1])


def _waiting_counts(store: JsonStore) -> dict[str, int]:
    albums = store.load(Album)
    placed = {p.album_id for p in store.load(Placement)}
    sorted_albums = albums_taking_part(store)
    sorted_artists = {album.artist_id for album in sorted_albums}
    confirmed = {a.artist_id for a in store.load(ArtistClusterAssignment) if a.confirmed}
    start_years = {artist.id for artist in store.load(Artist) if artist.start_year}
    overfull = 0
    if all(store.exists(entity) for entity in _LAYOUT_ENTITIES):
        fill = BrowseQueries(store).shelf_fill()
        overfull = sum(
            1
            for shelf in store.load(Shelf)
            # Over an estimated width says the shelf needs measuring, not that it is too full.
            if shelf.width_measured and fill.get(shelf.id, (0, 0.0))[1] > shelf.width_cm
        )
    to_check = {a for a in sorted_artists if a not in confirmed or a not in start_years}
    shifted = {shift.artist_id for shift in cluster_shifts(store)}
    return {
        "matches": len(store.load(MatchProposal)),
        "families": len(family_suggestions(store)),
        "artists": len(to_check),
        "shifts": len(shifted),
        "rule_suggestions": len(rule_suggestions(store)),
        # An artist can be in both; the menu and the steps count it once.
        "artists_in_all": len(to_check | shifted),
        "widths": sum(1 for album in sorted_albums if not album.width_confirmed),
        "unlinked": sum(1 for album in sorted_albums if album.release_id is None),
        "gone": sum(1 for a in albums if a.left_discogs and not a.kept_after_discogs),
        "overfull": overfull,
        "unplaced": sum(1 for album in sorted_albums if album.id not in placed),
    }


def menu_counts(store: JsonStore) -> dict[str, int]:
    """The counts shown behind menu items, by the blueprint or endpoint they belong to."""
    counts = waiting_counts(store)
    return {
        "unplaced": counts["unplaced"],
        "artists": counts["artists_in_all"],
        "families": counts["families"],
        "storage": counts["overfull"],
        "rules": counts["rule_suggestions"],
        "discogs": counts["matches"] + counts["gone"],
    }
