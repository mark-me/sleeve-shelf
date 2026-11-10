"""Tests for recognising a sleeve on a photo, and saying where the album goes back."""

import io

import cv2
import numpy as np
import pytest
from PIL import Image

from sleeve_shelf.access import set_password
from sleeve_shelf.domain import Album, Artist, ArtistClusterAssignment, Cabinet, Cluster, Placement, Shelf
from sleeve_shelf.fetching import recognition
from sleeve_shelf.fetching.covers import cover_name
from sleeve_shelf.fetching.recognition import FEATURES_FILE, read_photo, recognise
from sleeve_shelf.ingestion.cover_matching import CoverIndex, describe_cover, is_sure, Candidate
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.web import login
from sleeve_shelf.web.app import create_app

PASSWORD = "a long enough password"


def _cover(seed: int) -> np.ndarray:
    """A sleeve of its own: shapes and lines in colours chosen by the seed."""
    rng = np.random.default_rng(seed)
    image = np.full((600, 600, 3), rng.integers(0, 255, 3).tolist(), np.uint8)
    for _ in range(40):
        colour = rng.integers(0, 255, 3).tolist()
        x, y = (int(v) for v in rng.integers(0, 600, 2))
        kind = rng.integers(0, 3)
        if kind == 0:
            cv2.circle(image, (x, y), int(rng.integers(10, 80)), colour, -1)
        elif kind == 1:
            cv2.rectangle(image, (x, y), (x + int(rng.integers(10, 120)), y + int(rng.integers(10, 120))), colour, -1)
        else:
            cv2.line(image, (x, y), tuple(int(v) for v in rng.integers(0, 600, 2)), colour, int(rng.integers(2, 8)))
    cv2.putText(image, f"ALBUM {seed}", (40, 560), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 4)
    return image


def _photo(cover: np.ndarray, seed: int = 1) -> bytes:
    """The sleeve as a phone sees it: at an angle on a table, a little darker, as a JPEG."""
    rng = np.random.default_rng(seed)
    canvas = np.full((1600, 1200, 3), (90, 70, 50), np.uint8)
    corners = np.float32([[200, 300], [1000, 360], [960, 1150], [180, 1100]])
    corners += rng.uniform(-30, 30, corners.shape).astype(np.float32)
    h, w = cover.shape[:2]
    matrix = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), corners)
    warped = cv2.warpPerspective(cover, matrix, (1200, 1600))
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), matrix, (1200, 1600))
    canvas[mask > 0] = warped[mask > 0]
    canvas = cv2.convertScaleAbs(canvas, alpha=0.85, beta=-10)
    return cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()


def _collection(tmp_path, covers=6):
    """Albums 1 to covers, each with a sleeve of its own kept as its cover.

    All stand on one shelf but the last, which stands nowhere yet.
    """
    store = JsonStore(tmp_path)
    store.save(Cluster, [Cluster(1, "Rock", 0)])
    store.save(Artist, [Artist(1, "The Band", start_year=1968)])
    store.save(ArtistClusterAssignment, [ArtistClusterAssignment(1, 1, True)])
    folder = tmp_path / "covers" / "albums"
    folder.mkdir(parents=True)
    albums = []
    for number in range(1, covers + 1):
        url = f"https://i.discogs.com/cover-{number}.jpg"
        cv2.imwrite(str(folder / cover_name(url)), _cover(number))
        albums.append(Album(number, 1, f"Album {number}", original_release_year=1968 + number, cover_image_url=url))
    store.save(Album, albums)
    store.save(Cabinet, [Cabinet(1, "Kast", position=0)])
    store.save(Shelf, [Shelf(1, 1, "a", width_cm=60.0, position=0)])
    store.save(Placement, [Placement(number, 1, number - 1) for number in range(1, covers)])
    return store


@pytest.fixture
def store(tmp_path):
    recognition._indexes.clear()
    login._photos.clear()
    login._pages.clear()
    return _collection(tmp_path / "data")


@pytest.fixture
def client(store):
    return create_app(store.data_dir).test_client()


def test_a_photo_of_a_sleeve_is_recognised_with_certainty(store):
    found = recognise(store, _photo(_cover(3)))

    assert found.readable and found.sure
    assert found.album_ids[0] == 3


def test_the_features_are_kept_and_only_a_new_cover_is_described(store, monkeypatch):
    recognise(store, _photo(_cover(2)))
    assert (store.data_dir / "covers" / FEATURES_FILE).exists()

    described = []
    real = recognition.describe_cover
    monkeypatch.setattr(recognition, "describe_cover", lambda *args: described.append(args[0]) or real(*args))
    recognition._indexes.clear()
    assert recognise(store, _photo(_cover(2))).album_ids[0] == 2
    assert described == []

    # A seventh album with a sleeve: only that one is described.
    url = "https://i.discogs.com/cover-7.jpg"
    cv2.imwrite(str(store.data_dir / "covers" / "albums" / cover_name(url)), _cover(7))
    store.save(Album, [*store.load(Album), Album(7, 1, "Album 7", cover_image_url=url)])
    assert recognise(store, _photo(_cover(7))).album_ids[0] == 7
    assert described == [7]


def test_a_cover_of_ones_own_is_recognised_too(store):
    own = store.data_dir / "album_covers"
    own.mkdir()
    cv2.imwrite(str(own / "2-own.jpg"), _cover(42))
    albums = store.load(Album)
    albums[1].own_cover_file = "2-own.jpg"
    store.save(Album, albums)

    assert recognise(store, _photo(_cover(42))).album_ids[0] == 2


def test_what_is_no_photo_is_not_read():
    assert read_photo(b"not an image") is None
    assert read_photo(b"GIF89a" + bytes(100)) is None
    # Too many pixels to decode safely, whatever the file's size.
    big = io.BytesIO()
    Image.new("L", (9000, 8000)).save(big, "PNG")
    assert read_photo(big.getvalue()) is None
    small = io.BytesIO()
    Image.new("RGB", (640, 480), "red").save(small, "JPEG")
    assert read_photo(small.getvalue()).shape == (480, 640)


def test_a_photo_of_nothing_in_the_collection_recognises_nothing(store):
    found = recognise(store, _photo(_cover(99)))

    assert found.readable and not found.sure


def test_certainty_needs_enough_fitting_matches_and_a_clear_lead():
    assert is_sure([Candidate(1, 40, 41)])
    assert is_sure([Candidate(1, 40, 41), Candidate(2, 20, 30)])
    assert not is_sure([Candidate(1, 40, 41), Candidate(2, 21, 30)])
    assert not is_sure([Candidate(1, 10, 11)])
    assert not is_sure([])


def test_an_index_without_covers_finds_nothing():
    gray = cv2.cvtColor(_cover(1), cv2.COLOR_BGR2GRAY)
    assert CoverIndex([]).candidates(gray) == []
    assert describe_cover(1, np.zeros((300, 300), np.uint8)) is None


def test_home_has_the_camera_and_the_photo_says_where_the_album_goes_back(client):
    home = client.get("/").text
    assert 'action="/recognise/"' in home and 'capture="environment"' in home and 'name="photo"' in home

    page = client.post("/recognise/", data={"photo": (io.BytesIO(_photo(_cover(3))), "photo.jpg")})

    assert page.status_code == 200
    text = page.text
    assert "Album 3" in text and "Where it goes back" in text and "Kast &rsaquo; a" in text
    # Between its neighbours on the shelf, and a link to it there.
    assert "Album 2" in text and "Album 4" in text
    assert "/browse?shelf=1#album-3" in text


def test_an_album_without_a_place_says_so(client):
    text = client.post("/recognise/", data={"photo": (io.BytesIO(_photo(_cover(6))), "photo.jpg")}).text

    assert "Album 6" in text and "no place on the shelves yet" in text


def test_a_choice_leads_to_where_that_album_goes_back(client):
    text = client.get("/recognise/4").text

    assert "As you chose" in text and "Kast &rsaquo; a" in text
    assert client.get("/recognise/404").status_code == 404


def test_a_file_that_is_no_photo_is_refused(client):
    answer = client.post("/recognise/", data={"photo": (io.BytesIO(b"not an image"), "photo.jpg")})

    assert answer.status_code == 400 and "no photo that can be read" in answer.text
    assert client.post("/recognise/", data={}).status_code == 400


def test_a_visitor_may_recognise_a_sleeve_but_not_without_end(store, client, monkeypatch):
    set_password(store.data_dir, PASSWORD)
    visitor = create_app(store.data_dir).test_client()
    monkeypatch.setattr(login, "VISITOR_PHOTOS", 2)

    photo = _photo(_cover(3))
    for _ in range(2):
        answer = visitor.post("/recognise/", data={"photo": (io.BytesIO(photo), "photo.jpg")})
        assert answer.status_code == 200 and "Album 3" in answer.text
    assert visitor.post("/recognise/", data={"photo": (io.BytesIO(photo), "photo.jpg")}).status_code == 429
    assert visitor.get("/recognise/3").status_code == 200
    # An album without a place leads a visitor to its page, not to Manage.
    assert "tab=manage" not in visitor.get("/recognise/6").text
