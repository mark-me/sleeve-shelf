"""Tests for the Browse/Search queries."""

from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    Cabinet,
    Cluster,
    EraBand,
    Placement,
    ReleaseEnrichment,
    Shelf,
    Track,
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


def test_search_finds_a_song_and_says_which(tmp_path):
    from datetime import datetime

    store = JsonStore(tmp_path)
    store.save(Artist, [Artist(1, "Tom Waits"), Artist(2, "Nick Cave")])
    store.save(
        Album,
        [
            Album(1, 1, "Closing Time", release_id=10),
            Album(2, 2, "The Boatman's Call", release_id=20),
            Album(3, 1, "Martha My Dear"),
        ],
    )
    songs = (Track("A1", "Ol' '55", "3:58"), Track("A2", "Martha"), Track("B1", "Old Shoes"))
    store.save(
        ReleaseEnrichment,
        [
            ReleaseEnrichment(10, (), None, datetime(2026, 10, 18), tracklist=songs),
            # A release fetched before tracklists were kept has none to search.
            ReleaseEnrichment(20, (), None, datetime(2026, 10, 18)),
        ],
    )
    queries = BrowseQueries(store)

    def found(text):
        return [(row.title, row.tracks) for row in queries.search(text)]

    # Found by a song, also by part of its words, with case and accents ignored.
    assert found("ól 55") == [("Closing Time", (("A1", "Ol' '55"),))]
    # The artist and a song together; every song that matches is named.
    assert found("waits ol") == [("Closing Time", (("A1", "Ol' '55"), ("B1", "Old Shoes")))]
    assert found("waits old") == [("Closing Time", (("B1", "Old Shoes"),))]
    # Found by its title, an album names no song, also when one would match too.
    assert ("Martha My Dear", ()) in found("martha")
    assert ("Closing Time", (("A2", "Martha"),)) in found("martha")
    assert found("waits closing") == [("Closing Time", ())]
    # The words have to be in one song: one here and one in another does not count.
    assert found("martha shoes") == []
    assert found("cave martha") == []
