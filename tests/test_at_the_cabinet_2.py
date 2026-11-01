"""Tests for undoing a move, walking along the shelves, placing at once, and an own cover."""

import io

import pytest
from PIL import Image

from sleeve_shelf.cli import main
from sleeve_shelf.access import set_password
from sleeve_shelf.domain import Album, Artist, ArtistClusterAssignment, Cabinet, Cluster, FormatTokens, Placement, Shelf
from sleeve_shelf.library.albums import OWN_COVER_DIR, remove_own_cover, set_own_cover
from sleeve_shelf.persistence import BrowseQueries, JsonStore
from sleeve_shelf.web.app import create_app

LP = FormatTokens(1, False, False, False, ("LP",))


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 40), "red").save(out, "JPEG")
    return out.getvalue()


@pytest.fixture
def store(tmp_path) -> JsonStore:
    store = JsonStore(tmp_path / "data")
    store.save(Cluster, [Cluster(1, "Jazz", 0)])
    store.save(Artist, [Artist(1, "Ann", start_year=1950), Artist(2, "Bob", start_year=1950)])
    store.save(ArtistClusterAssignment, [ArtistClusterAssignment(1, 1, True), ArtistClusterAssignment(2, 1, True)])
    store.save(
        Album,
        [Album(i, artist, title, format_tokens=LP, computed_width_cm=1.0, original_release_year=1960 + i)
         for i, artist, title in ((1, 1, "A1"), (2, 1, "A2"), (3, 2, "B1"), (4, 1, "A3"), (5, 2, "B2"), (6, 2, "B3"))],
    )
    store.save(Cabinet, [Cabinet(1, "Kast", position=0)])
    store.save(Shelf, [Shelf(1, 1, "a", width_cm=50.0, position=0), Shelf(2, 1, "b", width_cm=50.0, position=1)])
    store.save(Placement, [Placement(1, 1, 0), Placement(2, 1, 1), Placement(3, 2, 0)])
    return store


@pytest.fixture
def client(store):
    return create_app(store.data_dir).test_client()


def _rows(store, shelf_id):
    return [row.album_id for row in BrowseQueries(store).shelf_albums(shelf_id)]


# Undo


def test_a_drag_can_be_put_back_with_what_the_answer_says(client, store):
    answer = client.post("/layout/move", json={"shelves": {"1": [1], "2": [2, 3]}}).get_json()
    assert _rows(store, 1) == [1] and _rows(store, 2) == [2, 3]
    assert answer["undo"]["1"] == [1, 2] and answer["undo"]["2"] == [3]

    assert client.post("/layout/move", json={"shelves": answer["undo"]}).status_code == 200
    assert _rows(store, 1) == [1, 2] and _rows(store, 2) == [3]


def test_an_album_from_the_tray_goes_back_to_the_tray(client, store):
    answer = client.post("/layout/move", json={"shelves": {"2": [4, 3]}}).get_json()
    assert _rows(store, 2) == [4, 3] and answer["undo"]["0"] == [4]

    client.post("/layout/move", json={"shelves": answer["undo"]})
    assert _rows(store, 2) == [3]
    assert 4 in {row.album_id for row in BrowseQueries(store).unplaced()}


def test_an_album_taken_off_a_shelf_comes_back_at_its_place(client, store):
    answer = client.post("/layout/move", json={"shelves": {"0": [1], "1": [2]}}).get_json()
    client.post("/layout/move", json={"shelves": answer["undo"]})
    assert _rows(store, 1) == [1, 2]


def test_sending_an_album_elsewhere_can_be_put_back_too(client, store):
    answer = client.post("/layout/send", json={"albums": [1], "shelf": 2}).get_json()
    assert _rows(store, 2) == [3, 1]
    client.post("/layout/move", json={"shelves": answer["undo"]})
    assert _rows(store, 1) == [1, 2] and _rows(store, 2) == [3]


def test_layout_has_the_bar_for_undoing(client):
    assert 'id="layout-undo"' in client.get("/layout/").text


# Walking


def test_a_shelf_says_which_of_how_many_it_is_and_can_be_walked(client):
    page = client.get("/browse?shelf=2").text
    assert "shelf 2 of 2" in page
    assert 'data-walk="prev" href="/browse?shelf=1"' in page and "page-walk.js" in page
    # At the last shelf there is nowhere further to go.
    assert 'data-walk="next" href=' not in page


def test_an_album_leads_on_along_the_shelves_and_over_to_the_next(client, store):
    assert BrowseQueries(store).neighbours(1)[0] is None
    before, after = BrowseQueries(store).neighbours(2)
    assert (before.album_id, after.album_id) == (1, 3)
    assert BrowseQueries(store).neighbours(3)[1] is None
    # One on no shelf has none.
    assert BrowseQueries(store).neighbours(4) == (None, None)

    page = client.get("/albums/2").text
    assert 'data-walk="prev" href="/albums/1"' in page and 'data-walk="next" href="/albums/3"' in page
    assert "Bob — B1" in page
    # The tab one is on stays.
    assert 'data-walk="next" href="/albums/3?tab=statistics"' in client.get("/albums/2?tab=statistics").text
    assert "data-walk" not in client.get("/albums/4").text.split("ss-tabs")[0]


# Placing at once


def test_placing_shows_first_what_it_does_and_changes_nothing(client, store):
    before = store.load(Placement)
    page = client.get("/unplaced/place").text
    assert "A3" in page and "B2" in page and 'name="album" value="4"' in page
    assert "to 3 albums" in page or "to 4 albums" in page
    assert store.load(Placement) == before
    assert 'href="/unplaced/place"' in client.get("/unplaced").text
    assert 'href="/unplaced/place"' in client.get("/dashboard/").text


def test_placing_stands_what_is_ticked_and_keeps_a_version(client, store):
    versions = len(store.snapshots())
    answer = client.post("/unplaced/place", data={"album": ["4", "5"]}, follow_redirects=True)
    assert "2 albums now stand at their spots" in answer.text
    standing = {p.album_id: p.shelf_id for p in store.load(Placement)}
    assert standing[4] == 1 and standing[5] == 2 and 6 not in standing
    # Next to their own artist, in the order of the sorting.
    assert _rows(store, 1) == [1, 2, 4] and _rows(store, 2) == [3, 5]
    assert len(store.snapshots()) > versions


def test_what_has_no_spot_is_not_placed(client, store):
    client.post("/unplaced/place", data={"album": ["1", "999"]})
    assert _rows(store, 1) == [1, 2]
    client.post("/unplaced/place", data={"album": ["4", "5", "6"]})
    assert "No album is waiting" in client.get("/unplaced/place").text


def test_a_visitor_cannot_place(store):
    set_password(store.data_dir, "a long enough password")
    visitor = create_app(store.data_dir).test_client()
    assert visitor.get("/unplaced/place").status_code == 302
    assert visitor.post("/unplaced/place", data={"album": ["4"]}).status_code == 403
    assert 4 not in {p.album_id for p in store.load(Placement)}


# An own cover


def test_an_own_cover_goes_before_the_one_from_discogs_everywhere(client, store):
    albums = store.load(Album)
    albums[0].cover_url = "https://i.discogs.com/small.jpg"
    albums[0].cover_image_url = "https://i.discogs.com/large.jpg"
    store.save(Album, albums)
    assert client.post("/albums/1/cover", data={"cover": (io.BytesIO(_jpeg()), "mine.jpg")}).status_code == 302

    file = store.load(Album)[0].own_cover_file
    assert (store.data_dir / OWN_COVER_DIR / file).exists()
    thumb = file.rsplit(".", 1)[0] + ".thumb.jpg"
    assert f'src="/albums/covers/{thumb}"' in client.get("/browse?shelf=1").text
    page = client.get("/albums/1").text
    assert f'src="/albums/covers/{thumb}"' in page and f'data-src="/albums/covers/{file}"' in page
    assert f'src="/albums/covers/{thumb}"' in client.get("/artists/1").text
    assert client.get(f"/albums/covers/{thumb}").status_code == 200
    assert "Remove my cover" in client.get("/albums/1?tab=manage").text

    client.post("/albums/1/cover/remove")
    assert store.load(Album)[0].own_cover_file is None and not (store.data_dir / OWN_COVER_DIR / file).exists()
    assert "https://i.discogs.com/small.jpg" in client.get("/albums/1").text


def test_an_album_without_any_cover_says_one_can_be_added(client):
    assert "Discogs has no cover for this release" in client.get("/albums/1?tab=manage").text


def test_a_new_cover_replaces_the_old_file(store):
    assert set_own_cover(store, 1, _jpeg())
    first = store.load(Album)[0].own_cover_file
    out = io.BytesIO()
    Image.new("RGB", (40, 40), "blue").save(out, "PNG")
    assert set_own_cover(store, 1, out.getvalue())
    second = store.load(Album)[0].own_cover_file
    assert second != first and second.endswith(".png")
    assert not (store.data_dir / OWN_COVER_DIR / first).exists()
    remove_own_cover(store, 1)
    assert not list((store.data_dir / OWN_COVER_DIR).iterdir())


def test_what_is_no_image_is_refused(client, store):
    answer = client.post("/albums/1/cover", data={"cover": (io.BytesIO(b"not an image"), "x.jpg")}, follow_redirects=True)
    assert "That file is not a JPEG" in answer.text and "Measured width" in answer.text
    assert "Choose an image" in client.post("/albums/1/cover", data={}, follow_redirects=True).text
    assert store.load(Album)[0].own_cover_file is None
    assert not set_own_cover(store, 999, _jpeg())


def test_a_visitor_sees_a_cover_but_cannot_change_it(store):
    assert set_own_cover(store, 1, _jpeg())
    file = store.load(Album)[0].own_cover_file
    set_password(store.data_dir, "a long enough password")
    visitor = create_app(store.data_dir).test_client()
    assert visitor.get(f"/albums/covers/{file}").status_code == 200
    assert visitor.post("/albums/1/cover/remove").status_code == 403
    assert store.load(Album)[0].own_cover_file == file


def test_a_cover_can_be_set_from_the_command_line(store, tmp_path, monkeypatch, capsys):
    image = tmp_path / "cover.jpg"
    image.write_bytes(_jpeg())
    monkeypatch.setenv("SLEEVE_SHELF_DATA_DIR", str(store.data_dir))
    main(["set-cover", "2", str(image)])
    assert "Cover of album 2 set" in capsys.readouterr().out
    assert store.load(Album)[1].own_cover_file
    with pytest.raises(SystemExit):
        main(["set-cover", "999", str(image)])
