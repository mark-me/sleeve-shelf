"""Tests for measuring the shelves: their inside widths, one after the other in walking order."""

import pytest

from sleeve_shelf.domain import Album, Artist, Cabinet, Placement, Shelf, ShelfType
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.shelving.storage import measure_shelf, measuring
from sleeve_shelf.web.app import create_app


def _collection(tmp_path):
    """Two cabinets walked in order, the second with a top-loader and kept outside the sorting.

    Shelf a holds three albums of 2 cm each against an estimated 5 cm.
    """
    store = JsonStore(tmp_path)
    store.save(Cabinet, [Cabinet(1, "Kast", position=0), Cabinet(2, "Koffer", position=1, outside_sorting=True)])
    store.save(
        Shelf,
        [Shelf(2, 1, "b", width_cm=30.0, position=1), Shelf(1, 1, "a", width_cm=5.0, position=0),
         Shelf(3, 2, "boven", width_cm=35.0, position=0, type=ShelfType.TOP_LOADER, width_measured=True)],
    )
    store.save(Artist, [Artist(1, "Cream")])
    store.save(Album, [Album(i, 1, f"Album {i}", manual_width_cm=2.0) for i in range(1, 4)])
    store.save(Placement, [Placement(i, 1, i - 1) for i in range(1, 4)])
    return store


@pytest.fixture
def store(tmp_path):
    return _collection(tmp_path / "data")


@pytest.fixture
def client(store):
    return create_app(store.data_dir).test_client()


def test_a_measured_width_is_kept_as_measured(store):
    measure_shelf(store, 1, 7.5)

    shelf = next(s for s in store.load(Shelf) if s.id == 1)
    assert (shelf.width_cm, shelf.width_measured) == (7.5, True)
    with pytest.raises(ValueError):
        measure_shelf(store, 1, 0)


def test_the_shelves_come_in_walking_order_with_what_they_hold(store):
    overview = measuring(store, {1: (3, 6.0)})

    assert [c["cabinet"].name for c in overview["cabinets"]] == ["Kast", "Koffer"]
    assert [row["shelf"].name for row in overview["cabinets"][0]["shelves"]] == ["a", "b"]
    first = overview["cabinets"][0]["shelves"][0]
    assert (first["albums"], first["filled_cm"], first["room_cm"]) == (3, 6.0, -1.0)
    assert overview["cabinets"][1]["shelves"][0]["outside"]
    assert (overview["measured_count"], overview["shelf_count"]) == (1, 3)


def test_the_screen_lists_every_shelf_top_loaders_too(client):
    page = client.get("/storage/measure").text

    assert page.index('id="shelf-1"') < page.index('id="shelf-2"') < page.index('id="shelf-3"')
    assert "Top-loader" in page and "outside the sorting" in page
    assert "1.0 cm too full" in page and "measured" in page
    assert 'action="/proposal/generate"' in page
    assert "/storage/measure" in client.get("/storage/").text


def test_saving_from_the_page_script_answers_with_the_new_row(client, store):
    answer = client.post("/storage/measure/1", data={"width_cm": "7,5"}, headers={"Accept": "application/json"})

    assert answer.status_code == 200
    row = answer.get_json()
    assert row["measured"] == 2 and row["shelves"] == 3
    assert "7.5 cm" in row["status"] and "1.5 cm left" in row["status"]
    # In Dutch the row writes a decimal comma.
    dutch = client.post(
        "/storage/measure/2", data={"width_cm": "41,5"}, headers={"Accept": "application/json", "Accept-Language": "nl"}
    )
    assert "41,5 cm" in dutch.get_json()["status"]


def test_saving_without_the_script_comes_back_to_the_shelf(client, store):
    assert client.post("/storage/measure/2", data={"width_cm": "40"}).headers["Location"] == "/storage/measure#shelf-2"
    assert next(s for s in store.load(Shelf) if s.id == 2).width_measured


def test_a_width_that_is_no_number_is_refused(client, store):
    answer = client.post("/storage/measure/1", data={"width_cm": "zes"}, headers={"Accept": "application/json"})
    assert answer.status_code == 400 and "above zero" in answer.get_json()["error"]
    plain = client.post("/storage/measure/1", data={"width_cm": "-3"})
    assert "error=" in plain.headers["Location"]
    assert not next(s for s in store.load(Shelf) if s.id == 1).width_measured
    assert client.post("/storage/measure/99", data={"width_cm": "3"}).status_code == 404
