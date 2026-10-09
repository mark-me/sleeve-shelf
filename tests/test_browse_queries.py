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
)
from sleeve_shelf.persistence import BrowseQueries, JsonStore


def test_an_album_is_where_its_placement_says(tmp_path):
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
            Placement(2, 1, 0),
            Placement(1, 1, 1),
            Placement(4, 3, 0),
        ],
    )
    queries = BrowseQueries(store)

    # On a shelf the albums stand in the order of their positions; an album without a
    # placement is on no shelf.
    assert [a.title for a in queries.shelf_albums(1)] == ["Closing Time", "Small Change"]
    assert queries.shelf_albums(2) == []
    assert [a.title for a in queries.shelf_albums(3)] == ["Orphans"]
    assert [s.album_count for s in queries.shelves()] == [2, 0, 1]
    assert [a.title for a in queries.unplaced()] == ["Mule Variations"]
