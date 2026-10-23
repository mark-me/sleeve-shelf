"""Tests for the Discogs screen: import, enrichment job, and match confirmation."""

import io
from datetime import datetime

import pytest

from sleeve_shelf import create_app
from sleeve_shelf.config import load_settings
from sleeve_shelf.covers import cover_name
from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistEnrichment,
    Cabinet,
    LocationRule,
    LocationRuleTarget,
    MasterEnrichment,
    MatchProposal,
    Placement,
    PlacementSource,
    ReleaseEnrichment,
    Shelf,
    Track,
)
from sleeve_shelf.ingestion.discogs_api import DiscogsError
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.versions import list_versions

EXPORT = (
    "Catalog#,Artist,Title,Label,Format,Rating,Released,release_id\n"
    'SD5061,Tom Waits,Closing Time,Asylum Records,"LP, Album",,1973,1874289\n'
    'VSPS-1,Woody Herman,The First Herd At Carnegie Hall,VSP,"LP, Comp",,1966,1126311\n'
    '151.102,The Birthday Party,The Bad Seed,4AD,"12"", EP",,1983,1965832\n'
    'CAD 207 CD,The Birthday Party,Junkyard,4AD,"CD, Album, RE",,1988,395825\n'
)


class _Client:
    def __init__(self, token):
        self.token = token

    def release(self, release_id):
        return ReleaseEnrichment(release_id, ("Blues Rock",), 77, datetime(2026, 10, 8), 1990)

    def master(self, master_id):
        return MasterEnrichment(master_id, 1973, datetime(2026, 10, 8))

    def image(self, url):
        return b"jpeg"

    def collection(self, progress=None):
        if progress is not None:
            progress(1, 1, len(COLLECTION))
        return COLLECTION


def _vinyl(release_id, artist, title):
    return {
        "id": release_id,
        "basic_information": {
            "title": title,
            "thumb": f"https://i.discogs.com/{release_id}.jpeg",
            "cover_image": f"https://i.discogs.com/{release_id}-large.jpeg",
            "artists": [{"name": artist, "join": ""}],
            "formats": [{"name": "Vinyl", "qty": "1", "descriptions": ["LP", "Album"]}],
        },
    }


COLLECTION = [
    _vinyl(1874289, "Tom Waits", "Closing Time"),
    _vinyl(1965832, "The Birthday Party", "Prayers On Fire"),
]


@pytest.fixture
def app(tmp_path):
    app = create_app(tmp_path / "data")
    app.config["DISCOGS_CLIENT_FACTORY"] = _Client
    store = JsonStore(tmp_path / "data")
    store.save(Artist, [Artist(1, "Tom Waits"), Artist(2, "Woody Herman And His Orchestra")])
    store.save(
        Album, [Album(1, 1, "Closing Time"), Album(2, 2, "The First Herd At Carnegie Hall")]
    )
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _store(app):
    return JsonStore(app.config["DATA_DIR"])


def _sync(app, client):
    """A round with Discogs, as the button starts it, waited for."""
    started = client.post("/discogs/sync")
    app.extensions["enrichment_job"].wait(10)
    return started


def _import(client):
    preview = client.post(
        "/discogs/import", data={"export": (io.BytesIO(EXPORT.encode()), "collection.csv")},
        follow_redirects=True,
    )
    assert preview.status_code == 200
    assert client.post("/discogs/import/confirm").status_code == 302
    return preview


def test_import_previews_and_only_changes_things_on_confirm(app, client):
    preview = client.post(
        "/discogs/import", data={"export": (io.BytesIO(EXPORT.encode()), "collection.csv")},
        follow_redirects=True,
    )

    assert "3</div>" in preview.text and "linked to your albums" in preview.text
    assert "1 release that is not vinyl is skipped." in preview.text
    assert all(album.release_id is None for album in _store(app).load(Album))

    client.post("/discogs/import/confirm")

    albums = _store(app).load(Album)
    assert albums[0].release_id == 1874289
    assert [album.title for album in albums][-1] == "The Bad Seed"
    page = client.get("/discogs/").text
    assert "Discogs: Woody Herman — The First Herd At Carnegie Hall" in page


def test_a_file_that_is_no_export_is_refused(client):
    response = client.post(
        "/discogs/import", data={"export": (io.BytesIO(b"Artist,Title\nx,y\n"), "wrong.csv")}
    )

    assert response.status_code == 400
    assert "missing columns" in response.text


def test_proposed_match_can_be_accepted(app, client):
    _import(client)

    client.post("/discogs/matches/2/accept")

    assert _store(app).load(Album)[1].release_id == 1126311
    assert _store(app).load(MatchProposal) == []


def test_declined_match_becomes_an_album_of_its_own(app, client):
    _import(client)

    client.post("/discogs/matches/2/reject")

    albums = _store(app).load(Album)
    assert albums[1].release_id is None
    assert (albums[-1].title, albums[-1].release_id) == (
        "The First Herd At Carnegie Hall",
        1126311,
    )
    assert _store(app).load(Artist)[-1].name == "Woody Herman"
    assert _store(app).load(MatchProposal) == []


def test_token_is_stored_and_only_shown_masked(app, client):
    assert client.post("/discogs/enrich/start").status_code == 400

    client.post("/discogs/token", data={"token": "abcdefgh1234"})

    assert load_settings(app.config["DATA_DIR"]).discogs_token == "abcdefgh1234"
    page = client.get("/discogs/").text
    assert "••••1234" in page and "abcdefgh" not in page


def test_fetching_alone_runs_in_the_background_and_fills_the_albums(app, client):
    _import(client)
    client.post("/discogs/token", data={"token": "secret"})
    # After an export the round has things to fetch, which can be done without a sync.
    page = client.get("/discogs/").text
    assert "Only fetch, without syncing" in page and 'ss-step-is-todo" id="step-fetch"' in page

    assert client.post("/discogs/enrich/start").status_code == 302
    app.extensions["enrichment_job"].wait(10)

    status = client.get("/discogs/enrich/status").get_json()
    assert (status["running"], status["outcome"], status["done"]) == (False, "finished", 3)
    assert status["albums"] == [2, 2] and status["synced"] is None
    album = _store(app).load(Album)[0]
    assert (album.master_id, album.original_release_year) == (77, 1973)
    page = client.get("/discogs/").text
    # Fetching alone skipped the sync's steps; the rest is done.
    assert 'ss-step-is-skipped" id="step-collection"' in page and 'ss-step-is-done" id="step-fetch"' in page
    assert "2 of 2 linked albums" in page and "Only fetch, without syncing" not in page


def test_a_round_brings_the_songs_to_search_and_to_the_album_page(app, client):
    class Songs(_Client):
        def release(self, release_id):
            fetched = super().release(release_id)
            songs = {1874289: (Track("A1", "Ol' '55", "3:58"), Track("A2", "I Hope That I Don't Fall In Love With You"))}
            return ReleaseEnrichment(
                release_id, fetched.styles, fetched.master_id, fetched.fetched_at, fetched.year,
                tracklist=songs.get(release_id, ()),
            )

    app.config["DISCOGS_CLIENT_FACTORY"] = Songs
    client.post("/discogs/token", data={"token": "secret"})
    _sync(app, client)
    results = client.get("/browse?q=fall+in+love").text
    assert "Closing Time" in results and "A2 &middot; I Hope That I Don&#39;t Fall In Love With You" in results

    # Closing Time as fetched before tracklists were kept: the next round asks for it again.
    _store(app).save(
        ReleaseEnrichment,
        [r if r.release_id != 1874289 else ReleaseEnrichment(1874289, ("Blues Rock",), 77, datetime(2026, 10, 1), 1990)
         for r in _store(app).load(ReleaseEnrichment)],
    )
    assert "The tracklist comes with the next fetch from Discogs." in client.get("/albums/1").text
    _sync(app, client)
    releases = {r.release_id: r for r in _store(app).load(ReleaseEnrichment)}
    # It got its tracklist back and kept its styles.
    assert releases[1874289].styles == ("Blues Rock",) and len(releases[1874289].tracklist) == 2
    album = client.get("/albums/1").text
    assert "Tracklist" in album and "Ol&#39; &#39;55" in album and "3:58" in album


def test_a_failing_lookup_is_reported(app, client):
    class Broken(_Client):
        def release(self, release_id):
            raise RuntimeError("boom")

    app.config["DISCOGS_CLIENT_FACTORY"] = Broken
    _import(client)
    client.post("/discogs/token", data={"token": "secret"})

    client.post("/discogs/enrich/start")
    app.extensions["enrichment_job"].wait(10)

    assert "RuntimeError: boom" in client.get("/discogs/").text


def test_a_sync_takes_the_collection_over_at_once_and_says_what_it_did(app, client):
    assert client.post("/discogs/sync").status_code == 400
    client.post("/discogs/token", data={"token": "secret"})

    started = _sync(app, client)

    assert started.headers["Location"] == "/discogs/#round"
    status = client.get("/discogs/enrich/status").get_json()
    assert (status["outcome"], status["collection"], status["releases"]) == ("finished", [1, 1], 2)
    assert status["synced"] == {"vinyl": 2, "added": 1, "matched": 1, "proposed": 0, "refreshed": 0, "gone": 0}
    albums = _store(app).load(Album)
    assert albums[0].release_id == 1874289
    assert (albums[-1].title, albums[-1].release_id) == ("Prayers On Fire", 1965832)
    # A sync brings the covers, for albums that were there and for new ones.
    assert albums[0].cover_url == "https://i.discogs.com/1874289.jpeg"
    assert albums[-1].cover_url == "https://i.discogs.com/1965832.jpeg"
    assert albums[0].cover_image_url == "https://i.discogs.com/1874289-large.jpeg"
    page = client.get("/discogs/").text
    assert "2 releases in your collection" in page and "1 new album" in page
    assert "formats brought up to date" not in page
    # A round that finds nothing new says so.
    _sync(app, client)
    assert "Nothing changed since the last time." in client.get("/discogs/").text
    assert page.count("ss-step-is-done") == 4
    # An export has no covers and leaves them alone.
    _import(client)
    assert _store(app).load(Album)[0].cover_url == "https://i.discogs.com/1874289.jpeg"
    assert len(_store(app).load(Album)) == 3


def test_sync_reports_albums_that_left_the_collection_and_keeps_them(app, client, monkeypatch):
    client.post("/discogs/token", data={"token": "secret"})
    _sync(app, client)
    monkeypatch.setitem(globals(), "COLLECTION", COLLECTION[:1])

    _sync(app, client)

    assert client.get("/discogs/enrich/status").get_json()["synced"]["gone"] == 1
    assert len(_store(app).load(Album)) == 3
    page = client.get("/discogs/").text
    assert "1 no longer on Discogs" in page
    assert 'id="waiting"' in page and 'id="gone"' in page and "Prayers On Fire" in page

    # Back in the collection, the mark goes again.
    monkeypatch.setitem(globals(), "COLLECTION", COLLECTION + [_vinyl(1965832, "The Birthday Party", "Prayers On Fire")])
    _sync(app, client)
    assert 'id="gone"' not in client.get("/discogs/").text


def test_sync_brings_the_format_of_linked_albums_up_to_date_and_an_export_does_not(app, client):
    client.post("/discogs/token", data={"token": "secret"})
    _import(client)
    album = _store(app).load(Album)[0]
    assert (album.format_tokens.qualifiers, album.computed_width_cm) == (("LP", "Album"), 0.5)
    heavy = _vinyl(1874289, "Tom Waits", "Closing Time")
    heavy["basic_information"]["formats"][0].update(qty="2", text="Blue, Gatefold, 180g")
    app.config["DISCOGS_CLIENT_FACTORY"] = type("Heavy", (_Client,), {"collection": lambda self, progress=None: [heavy]})

    _sync(app, client)

    assert "1 format brought up to date" in client.get("/discogs/").text
    album = _store(app).load(Album)[0]
    assert album.format_tokens.qualifiers == ("2xLP", "Album", "180", "Gat")
    assert album.computed_width_cm == 1.5

    # The export knows less; importing it again does not undo the sync.
    _import(client)
    assert _store(app).load(Album)[0].computed_width_cm == 1.5


def test_sync_reports_when_discogs_cannot_be_reached_or_the_collection_is_empty(app, client):
    class Unreachable(_Client):
        def collection(self, progress=None):
            raise DiscogsError("Discogs could not be reached: timed out")

    app.config["DISCOGS_CLIENT_FACTORY"] = Unreachable
    client.post("/discogs/token", data={"token": "secret"})

    _sync(app, client)

    page = client.get("/discogs/").text
    assert "Discogs could not be reached: timed out" in page and "Sync again to go on." in page
    assert 'ss-step-is-failed" id="step-collection"' in page
    assert all(album.release_id is None for album in _store(app).load(Album))

    app.config["DISCOGS_CLIENT_FACTORY"] = type("Empty", (_Client,), {"collection": lambda self, progress=None: []})
    _sync(app, client)
    assert "Your Discogs collection is empty." in client.get("/discogs/").text


def test_an_album_that_left_discogs_is_only_removed_after_confirming(app, client):
    client.post("/discogs/token", data={"token": "secret"})
    _sync(app, client)
    store = _store(app)
    store.save(Cabinet, [Cabinet(1, "Kast")])
    store.save(Shelf, [Shelf(1, 1, "a")])
    store.save(
        Placement,
        [
            Placement(1, 1, 0, PlacementSource.MANUAL),
            Placement(3, 1, 1, PlacementSource.MANUAL),
        ],
    )
    store.save(LocationRule, [LocationRule(1, LocationRuleTarget.ALBUM, 3, 1)])
    app.config["DISCOGS_CLIENT_FACTORY"] = type(
        "Sold", (_Client,), {"collection": lambda self, progress=None: COLLECTION[:1]}
    )
    _sync(app, client)

    # An album that is still in the collection cannot be removed this way.
    assert client.post("/discogs/gone/1/remove").status_code == 302
    assert len(_store(app).load(Album)) == 3

    assert "/discogs/gone/3/remove" in client.get("/discogs/").text
    question = client.get("/discogs/gone/3/remove").text
    assert "Remove this album?" in question and "Prayers On Fire" in question
    assert "Kast · a" in question
    # Asking changes nothing, and neither does another sync: the question returns.
    _sync(app, client)
    assert len(_store(app).load(Album)) == 3
    assert "/discogs/gone/3/remove" in client.get("/discogs/").text

    assert client.post("/discogs/gone/3/remove").status_code == 302

    store = _store(app)
    assert [album.id for album in store.load(Album)] == [1, 2]
    assert [placement.album_id for placement in store.load(Placement)] == [1]
    assert store.load(LocationRule) == []
    # The layout from before the removal is kept as a version; the artist stays.
    assert [(v.label, v.album_count) for v in list_versions(store)] == [("before removing an album", 2)]
    assert store.load(Artist)[-1].name == "The Birthday Party"
    assert 'id="gone"' not in client.get("/discogs/").text


def test_a_round_brings_the_picture_of_an_artist(app, client):
    class Pictured(_Client):
        def collection(self, progress=None):
            release = _vinyl(1874289, "Tom Waits", "Closing Time")
            release["basic_information"]["artists"][0]["id"] = 82294
            return [release]

        def artist(self, artist_id):
            return ArtistEnrichment(
                artist_id, "https://i.discogs.com/tw.jpeg", "https://i.discogs.com/tw150.jpeg",
                datetime(2026, 10, 9), member_ids=(),
            )

    app.config["DISCOGS_CLIENT_FACTORY"] = Pictured
    client.post("/discogs/token", data={"token": "secret"})
    _sync(app, client)

    # The sync names the artist on Discogs, and the round goes on to fetch the picture.
    assert [a.discogs_artist_id for a in _store(app).load(Artist)] == [82294, None]
    done = client.get("/discogs/").text
    assert "1 of 1 artists" in done and "1 artist is not named on Discogs" in done
    page = client.get("/artists/1").text
    # Fetched, the picture is shown from the data directory, not from Discogs any more.
    thumb = cover_name("https://i.discogs.com/tw150.jpeg")
    large = cover_name("https://i.discogs.com/tw.jpeg")
    assert f'src="/covers/artists/{thumb}"' in page and "Show the picture larger" in page
    assert f'data-src="/covers/artists/{large}"' in page
    assert "i.discogs.com/tw" not in page
    assert client.get(f"/covers/artists/{thumb}").data == b"jpeg"
    # An artist without a picture has the page as it was.
    assert "ss-cover-zoom" not in client.get("/artists/2").text
    # In the list the pictured artist shows its picture, and the other keeps the space.
    # Searching lists both artists together (the list is otherwise one letter at a time).
    listed = client.get("/artists/?q=o").text
    assert f'src="/covers/artists/{thumb}"' in listed and "ss-cover-empty" in listed


def test_an_album_that_left_discogs_can_be_kept_without_being_asked_again(app, client):
    client.post("/discogs/token", data={"token": "secret"})
    _sync(app, client)
    app.config["DISCOGS_CLIENT_FACTORY"] = type(
        "Sold", (_Client,), {"collection": lambda self, progress=None: COLLECTION[:1]}
    )
    _sync(app, client)
    assert "/discogs/gone/3/remove" in client.get("/discogs/").text

    assert client.post("/discogs/gone/3/keep").status_code == 302

    page = client.get("/discogs/").text
    assert "/discogs/gone/3/remove" not in page
    assert "Kept although not on Discogs (1)" in page and "/discogs/gone/3/ask-again" in page
    assert len(_store(app).load(Album)) == 3
    # The next sync does not ask again.
    _sync(app, client)
    assert client.get("/discogs/enrich/status").get_json()["synced"]["gone"] == 0
    assert "/discogs/gone/3/remove" not in client.get("/discogs/").text

    # Taking it back lists the album as gone once more.
    client.post("/discogs/gone/3/ask-again")
    assert "/discogs/gone/3/remove" in client.get("/discogs/").text

    # An album that is still on Discogs cannot be marked, and one that returns loses the mark.
    client.post("/discogs/gone/1/keep")
    assert not _store(app).load(Album)[0].kept_after_discogs
    client.post("/discogs/gone/3/keep")
    app.config["DISCOGS_CLIENT_FACTORY"] = _Client
    _sync(app, client)
    album = _store(app).load(Album)[2]
    assert (album.left_discogs, album.kept_after_discogs) == (False, False)


def test_a_match_confirmed_after_a_sync_brings_the_cover_of_its_release(app, client):
    class Renamed(_Client):
        def collection(self, progress=None):
            # The release is titled a little differently than the album was loaded.
            return [_vinyl(1874289, "Tom Waits", "Closing Time (Remastered)")]

    app.config["DISCOGS_CLIENT_FACTORY"] = Renamed
    client.post("/discogs/token", data={"token": "secret"})
    _sync(app, client)

    # Not the same title, so the link waits for a yes — and the album has no release yet.
    album = _store(app).load(Album)[0]
    assert (album.release_id, album.cover_url) == (None, None)
    assert "1</div>" in client.get("/discogs/").text

    client.post("/discogs/matches/1/accept")

    album = _store(app).load(Album)[0]
    assert album.release_id == 1874289
    assert album.cover_url == "https://i.discogs.com/1874289.jpeg"
    assert album.cover_image_url == "https://i.discogs.com/1874289-large.jpeg"


def test_the_screen_shows_the_round_and_what_waits_for_the_owner(app, client):
    class Renamed(_Client):
        def collection(self, progress=None):
            return [_vinyl(1874289, "Tom Waits", "Closing Time (Remastered)")]

    app.config["DISCOGS_CLIENT_FACTORY"] = Renamed
    # Without a token that is the thing to do, and the token block stands open.
    page = client.get("/discogs/").text
    assert "needed first" in page and '<details class="ss-card mt-4" id="token-block" open>' in page
    assert ">Sync</button>" in page and "disabled>Sync" in page.replace('type="submit" ', "")
    client.post("/discogs/token", data={"token": "secret"})
    page = client.get("/discogs/").text
    assert "set: ••••cret" in page and 'id="token-block" >' in page
    # The steps of a round, in the order they are done; nothing waits yet.
    assert page.index('id="step-collection"') < page.index('id="step-import"') < page.index('id="step-fetch"') < page.index('id="step-store"')
    assert 'id="waiting"' not in page

    _sync(app, client)

    # The match it is not sure of waits for the owner; the rest of the round went on.
    page = client.get("/discogs/").text
    assert 'id="waiting"' in page and "1 match to confirm" in page
    client.post("/discogs/matches/1/accept")
    assert 'id="waiting"' not in client.get("/discogs/").text


def test_a_running_round_shows_its_step_and_a_stop_button_and_starts_no_second(app, client):
    import threading

    gate = threading.Event()

    class Slow(_Client):
        def collection(self, progress=None):
            progress(1, 3, 250)
            gate.wait(5)
            return COLLECTION

    app.config["DISCOGS_CLIENT_FACTORY"] = Slow
    client.post("/discogs/token", data={"token": "secret"})
    client.post("/discogs/sync")
    try:
        page = client.get("/discogs/").text
        assert 'ss-step-is-now" id="step-collection"' in page and 'data-part="collection"' in page
        assert 'id="collection-bar"' in page
        assert "1 of 3 · 250 releases" in page and ">Stop</button>" in page and ">Sync</button>" not in page
        # Pressing again while it runs starts nothing new.
        assert client.post("/discogs/sync").status_code == 302
    finally:
        gate.set()
        app.extensions["enrichment_job"].wait(10)
    assert client.get("/discogs/enrich/status").get_json()["outcome"] == "finished"


def test_an_uploaded_export_can_be_discarded(app, client):
    preview = client.post(
        "/discogs/import", data={"export": (io.BytesIO(EXPORT.encode()), "collection.csv")},
        follow_redirects=True,
    )
    assert "Nothing has changed yet." in preview.text

    discarded = client.post("/discogs/import/discard")

    assert discarded.headers["Location"] == "/discogs/#round"
    assert "Nothing has changed yet." not in client.get("/discogs/").text
    assert all(album.release_id is None for album in _store(app).load(Album))