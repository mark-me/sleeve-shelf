"""Tests for the Browse/Search queries."""

from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    Cabinet,
    Cluster,
    EraBand,
    Placement,
    Shelf,
    UnitType,
)
from sleeve_shelf.persistence import BrowseQueries, JsonStore


def test_most_specific_placement_decides_where_an_album_is(tmp_path):
    store = JsonStore(tmp_path)
    store.save(Cabinet, [Cabinet(1, "Kast")])
    store.save(Shelf, [Shelf(1, 1, "a"), Shelf(2, 1, "b"), Shelf(3, 1, "c")])
    store.save(Cluster, [Cluster(1, "Rock")])
    store.save(Artist, [Artist(1, "Tom Waits")])
    store.save(ArtistClusterAssignment, [ArtistClusterAssignment(1, 1, confirmed=True)])
    store.save(EraBand, [EraBand(1, 1, "early", 0), EraBand(2, 1, "late", 1)])
    store.save(
        Album,
        [
            Album(1, 1, "Small Change", era_band_id=1),
            Album(2, 1, "Closing Time", era_band_id=1),
            Album(3, 1, "Mule Variations", era_band_id=2),
            Album(4, 1, "Orphans", era_band_id=2),
        ],
    )
    store.save(
        Placement,
        [
            Placement(UnitType.ARTIST, 1, 1, 0),
            Placement(UnitType.ERA_BAND, 2, 2, 0),
            Placement(UnitType.ALBUM, 4, 3, 0),
        ],
    )
    queries = BrowseQueries(store)

    # The early band has no placement of its own, so it follows the artist;
    # within a unit the albums stand alphabetically.
    assert [a.title for a in queries.shelf_albums(1)] == ["Closing Time", "Small Change"]
    assert [a.title for a in queries.shelf_albums(2)] == ["Mule Variations"]
    assert [a.title for a in queries.shelf_albums(3)] == ["Orphans"]
    assert [s.album_count for s in queries.shelves()] == [2, 1, 1]
    assert queries.unplaced() == []
