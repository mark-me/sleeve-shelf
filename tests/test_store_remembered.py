"""Tests for what the store remembers, and for reading only the albums a page needs."""

from sleeve_shelf.config import load_settings, save_settings
from sleeve_shelf.domain import Album, Artist, Cabinet, Cluster, Placement, Shelf
from sleeve_shelf.insights.connections import network, set_unrelated
from sleeve_shelf.persistence import BrowseQueries, JsonStore


def _collection(tmp_path) -> JsonStore:
    store = JsonStore(tmp_path)
    store.save(Cluster, [Cluster(1, "Jazz", 0)])
    store.save(Artist, [Artist(1, "Chet Baker"), Artist(2, "Chet Baker Quartet")])
    store.save(Album, [Album(1, 1, "One"), Album(2, 2, "Two"), Album(3, 1, "Three"), Album(4, 1, "Four")])
    store.save(Cabinet, [Cabinet(1, "Kast")])
    store.save(Shelf, [Shelf(1, 1, "a"), Shelf(2, 1, "b")])
    store.save(Placement, [Placement(3, 1, 0), Placement(1, 1, 1), Placement(2, 2, 0)])
    return store


def test_an_answer_is_kept_until_the_data_or_the_settings_change(tmp_path):
    store = _collection(tmp_path)
    asked = []

    def work():
        asked.append(1)
        return len(asked)

    assert store.remembered("answer", work) == 1
    assert store.remembered("answer", work) == 1
    # Another store on the same directory, as a new request has, knows it too.
    assert JsonStore(tmp_path).remembered("answer", work) == 1

    store.save(Album, [*store.load(Album), Album(5, 1, "Five")])
    assert store.remembered("answer", work) == 2

    settings = load_settings(tmp_path)
    settings.table_records = 7
    save_settings(tmp_path, settings)
    assert store.remembered("answer", work) == 3
    # Each question is kept on its own.
    assert store.remembered("other", lambda: "else") == "else"


def test_the_network_follows_what_the_owner_says(tmp_path):
    store = _collection(tmp_path)
    assert len(network(store).links) == 1
    assert network(store) is network(store)

    set_unrelated(store, 1, 2, True)
    assert network(store).links == ()


def test_the_albums_per_shelf_are_those_of_each_shelf_on_its_own(tmp_path):
    queries = BrowseQueries(_collection(tmp_path))
    per_shelf = queries.by_shelf()
    assert [row.album_id for row in per_shelf[1]] == [3, 1]
    assert per_shelf == {1: queries.shelf_albums(1), 2: queries.shelf_albums(2)}


def test_only_the_albums_asked_for_are_read(tmp_path):
    queries = BrowseQueries(_collection(tmp_path))
    every = {row.album_id: row for row in queries.everything()}
    assert queries.albums([]) == {}
    # One without a place is found too, and one that is not there is not.
    assert queries.albums([2, 4, 99, 2]) == {2: every[2], 4: every[4]}
