"""Tests for listening to an album: finding it at Deezer, Discogs' videos, and the album's page."""

from datetime import datetime, timedelta

import pytest

from sleeve_shelf import create_app
from sleeve_shelf.domain import Album, AlbumListening, Artist
from sleeve_shelf.ingestion.deezer import (
    DeezerAlbum,
    DeezerError,
    DeezerTrack,
    best_album,
    first_artist,
)
from sleeve_shelf.listening import LOOK_AGAIN_AFTER, listening, turn_down
from sleeve_shelf.persistence import JsonStore


def _candidate(id_, title, artist):
    return {"id": id_, "title": title, "artist": {"name": artist}, "cover_medium": f"https://cdn/{id_}.jpg"}


def test_the_album_found_is_ours_and_not_a_live_record_or_a_remix():
    found = best_album("Creedence Clearwater Revival", "Green River", [
        _candidate(1, "Green River (Live)", "Creedence Clearwater Revival"),
        _candidate(2, "Green River (Remastered 1985)", "Creedence Clearwater Revival"),
        _candidate(3, "Green River", "Some Tribute Band"),
    ])
    assert found.id == 2

    # The same title by another artist is not ours, nor is a remix.
    assert best_album("David Bowie", '"Heroes"', [_candidate(4, "Heroes", "DJ Aiblo")]) is None
    assert best_album("David Bowie", '"Heroes"', [_candidate(5, '"Heroes" (Klax Remix)', "David Bowie")]) is None
    # When ours is a live record, the live record is it.
    assert best_album("Tami Neilson", "Kingmaker (Live)", [_candidate(6, "Kingmaker (Live)", "Tami Neilson")]).id == 6


def test_the_first_of_several_artists_is_searched_for_too():
    assert first_artist("Duke Ellington, Charles Mingus") == "Duke Ellington"
    assert first_artist("Cannonball Adderley With Bill Evans") == "Cannonball Adderley"
    assert first_artist("Morphine (2)") == "Morphine"


class _Deezer:
    def __init__(self, album=None, fail=False):
        self.album, self.fail, self.searches = album, fail, 0

    def find_album(self, artist, title):
        self.searches += 1
        if self.fail:
            raise DeezerError("offline")
        return self.album

    def tracks(self, album_id):
        if self.fail:
            raise DeezerError("offline")
        return [DeezerTrack("Martha", 271, "https://cdnt-preview/1.mp3"), DeezerTrack("Rosie", 245, None)]


class _Discogs:
    def __init__(self, token=""):
        self.asked = 0

    def videos(self, release_id):
        self.asked += 1
        return (("Tom Waits - Martha", "https://www.youtube.com/watch?v=y9Mse62NFl4"),)


CLOSING_TIME = DeezerAlbum(301, "Closing Time", "Tom Waits", "https://cdn/301.jpg")


@pytest.fixture
def store(tmp_path):
    store = JsonStore(tmp_path)
    store.save(Artist, [Artist(1, "Tom Waits")])
    store.save(Album, [Album(1, 1, "Closing Time", release_id=1874289), Album(2, 1, "Bourbon Jesus")])
    return store


def test_what_was_found_is_kept_and_the_previews_are_fetched_each_time(store):
    deezer, discogs = _Deezer(CLOSING_TIME), _Discogs()

    first = listening(store, 1, deezer, discogs)
    again = listening(store, 1, deezer, discogs)

    assert first.album == CLOSING_TIME and [t.title for t in again.tracks] == ["Martha", "Rosie"]
    assert first.videos[0].youtube_id == "y9Mse62NFl4"
    # Deezer was searched, and Discogs asked, only the first time.
    assert (deezer.searches, discogs.asked) == (1, 1)
    assert listening(store, 99, deezer, discogs) is None


def test_an_album_deezer_lacks_is_looked_for_again_only_after_a_while(store):
    deezer = _Deezer(None)
    assert listening(store, 2, deezer, None).album is None
    listening(store, 2, deezer, None)
    assert deezer.searches == 1

    record = store.load(AlbumListening)[0]
    store.save(AlbumListening, [AlbumListening(2, datetime.now() - LOOK_AGAIN_AFTER - timedelta(days=1))])
    assert record.deezer_album_id is None
    listening(store, 2, deezer, None)
    assert deezer.searches == 2


def test_without_a_connection_nothing_is_taken_as_not_found(store):
    offline = listening(store, 2, _Deezer(fail=True), None)
    assert offline.unreachable and offline.album is None

    # Once Deezer answers, it is asked straight away.
    online = _Deezer(CLOSING_TIME)
    assert listening(store, 2, online, None).album == CLOSING_TIME and online.searches == 1


def test_an_album_turned_down_is_not_offered_again(store):
    deezer = _Deezer(CLOSING_TIME)
    listening(store, 1, deezer, None)
    turn_down(store, 1)

    after = listening(store, 1, deezer, None)
    assert after.album is None and after.turned_down and deezer.searches == 1


def test_the_album_page_loads_previews_and_videos_after_it_is_shown(tmp_path):
    from openpyxl import Workbook

    app = create_app(tmp_path / "data")
    app.config["DEEZER_CLIENT_FACTORY"] = lambda: _Deezer(CLOSING_TIME)
    app.config["DISCOGS_CLIENT_FACTORY"] = _Discogs
    client = app.test_client()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Kastindeling"
    sheet.append(["Locatie", "Vak", "Cluster", "Era-band (artiest)", "Artiest", "Titel"])
    sheet.append(["Kast", "a", "Singer-Songwriter", "1970s", "Tom Waits", "Closing Time"])
    path = tmp_path / "layout.xlsx"
    workbook.save(path)
    with path.open("rb") as file:
        client.post("/setup/upload", data={"workbook": (file, "layout.xlsx")})
    client.post("/setup/confirm")
    store = JsonStore(app.config["DATA_DIR"])
    albums = store.load(Album)
    albums[0].release_id = 1874289
    store.save(Album, albums)

    page = client.get("/albums/1").text
    assert 'id="listen"' in page and "/albums/1/listen" in page and "Looking for previews" in page

    part = client.get("/albums/1/listen").text
    assert 'data-preview="https://cdnt-preview/1.mp3"' in part and "Open in Deezer" in part
    assert 'data-youtube="y9Mse62NFl4"' in part and "Videos on Discogs" in part
    # A track without a preview cannot be played.
    assert part.count("disabled") == 1

    client.post("/albums/1/listen/not-this")
    assert "Open in Deezer" not in client.get("/albums/1/listen").text
    assert client.get("/albums/99/listen").status_code == 404


def test_browse_has_a_play_button_that_gets_the_previews_without_asking_discogs(tmp_path):
    from openpyxl import Workbook

    asked = []

    class _NoDiscogs:
        def __init__(self, token=""):
            asked.append(token)

    app = create_app(tmp_path / "data")
    app.config["DEEZER_CLIENT_FACTORY"] = lambda: _Deezer(CLOSING_TIME)
    app.config["DISCOGS_CLIENT_FACTORY"] = _NoDiscogs
    client = app.test_client()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Kastindeling"
    sheet.append(["Locatie", "Vak", "Cluster", "Era-band (artiest)", "Artiest", "Titel"])
    sheet.append(["Kast", "a", "Singer-Songwriter", "1970s", "Tom Waits", "Closing Time"])
    path = tmp_path / "layout.xlsx"
    workbook.save(path)
    with path.open("rb") as file:
        client.post("/setup/upload", data={"workbook": (file, "layout.xlsx")})
    client.post("/setup/confirm")

    for page in ("/browse", "/browse?q=closing"):
        text = client.get(page).text
        assert 'data-play-album="/albums/1/previews"' in text and "/static/browse-play.js" in text, page
    # A search result still leads to the album's shelf.
    assert 'class="ss-row-link" href="/browse?shelf=1#album-1"' in client.get("/browse?q=closing").text

    previews = client.get("/albums/1/previews").get_json()
    # Only the tracks that have a preview; Discogs is left alone.
    assert previews["album"] == "Closing Time" and previews["tracks"] == [
        {"title": "Martha", "preview": "https://cdnt-preview/1.mp3"}
    ]
    assert asked == [] and client.get("/albums/99/previews").status_code == 404


def test_only_web_addresses_are_taken_as_videos(store):
    import json

    from sleeve_shelf.ingestion.discogs_api import DiscogsClient, is_web_address

    assert is_web_address("https://www.youtube.com/watch?v=y9Mse62NFl4")
    assert not any(is_web_address(a) for a in ("javascript:alert(1)", " JavaScript:alert(1)", "data:text/html,x", "//x", "", None))

    release = {"videos": [
        {"title": "Martha", "uri": "https://www.youtube.com/watch?v=y9Mse62NFl4"},
        {"title": "Click me", "uri": "javascript:alert(document.cookie)"},
    ]}
    client = DiscogsClient("", fetch=lambda request: json.dumps(release).encode(), sleep=lambda s: None)
    assert client.videos(1) == (("Martha", "https://www.youtube.com/watch?v=y9Mse62NFl4"),)

    # A link kept before addresses were checked is left out when the page is shown.
    store.save(AlbumListening, [AlbumListening(
        1, datetime.now(), video_titles=("Martha", "Click me"),
        video_urls=("https://www.youtube.com/watch?v=y9Mse62NFl4", "javascript:alert(1)"),
    )])
    shown = listening(store, 1, _Deezer(None), None)
    assert [video.title for video in shown.videos] == ["Martha"]
