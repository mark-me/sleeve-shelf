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
    Placement,
    PlacementSource,
    Shelf,
    MasterEnrichment,
    MatchProposal,
    ReleaseEnrichment,
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

    def collection(self):
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


def test_enrichment_runs_in_the_background_and_fills_the_albums(app, client):
    _import(client)
    client.post("/discogs/token", data={"token": "secret"})
    assert "2 linked albums still have to be fetched." in client.get("/discogs/").text

    assert client.post("/discogs/enrich/start").status_code == 302
    app.extensions["enrichment_job"].wait(10)

    status = client.get("/discogs/enrich/status").get_json()
    assert (status["running"], status["outcome"], status["done"]) == (False, "finished", 3)
    assert status["albums"] == [2, 2]
    album = _store(app).load(Album)[0]
    assert (album.master_id, album.original_release_year) == (77, 1973)
    page = client.get("/discogs/").text
    assert "Everything has been fetched." in page and "2 of 2 linked albums" in page


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


def test_sync_previews_the_collection_and_only_changes_things_on_confirm(app, client):
    assert client.post("/discogs/sync").status_code == 400
    client.post("/discogs/token", data={"token": "secret"})

    preview = client.post("/discogs/sync", follow_redirects=True)

    assert "taking over your Discogs collection" in preview.text
    assert "2</div>" in preview.text and "vinyl releases in your collection" in preview.text
    assert all(album.release_id is None for album in _store(app).load(Album))
    # Left without taking it over, the Discogs screen says the sync is still waiting.
    assert "Nothing has changed yet." in client.get("/discogs/").text

    assert client.post("/discogs/import/confirm").status_code == 302
    assert "Nothing has changed yet." not in client.get("/discogs/").text

    albums = _store(app).load(Album)
    assert albums[0].release_id == 1874289
    assert (albums[-1].title, albums[-1].release_id) == ("Prayers On Fire", 1965832)
    # A sync brings the covers, for albums that were there and for new ones.
    assert albums[0].cover_url == "https://i.discogs.com/1874289.jpeg"
    assert albums[-1].cover_url == "https://i.discogs.com/1965832.jpeg"
    assert albums[0].cover_image_url == "https://i.discogs.com/1874289-large.jpeg"
    # An export has no covers and leaves them alone.
    _import(client)
    assert _store(app).load(Album)[0].cover_url == "https://i.discogs.com/1874289.jpeg"
    # Nothing is left waiting: confirming again does nothing.
    client.post("/discogs/import/confirm")
    assert len(_store(app).load(Album)) == 3


def test_sync_reports_albums_that_left_the_collection_and_keeps_them(app, client, monkeypatch):
    client.post("/discogs/token", data={"token": "secret"})
    client.post("/discogs/sync")
    client.post("/discogs/import/confirm")
    monkeypatch.setitem(globals(), "COLLECTION", COLLECTION[:1])

    preview = client.post("/discogs/sync", follow_redirects=True)
    client.post("/discogs/import/confirm")

    assert "1 album is no longer in your Discogs collection" in preview.text
    assert "Prayers On Fire" in preview.text
    assert len(_store(app).load(Album)) == 3
    page = client.get("/discogs/").text
    assert 'id="gone"' in page and "Prayers On Fire" in page

    # Back in the collection, the mark goes again.
    monkeypatch.setitem(globals(), "COLLECTION", COLLECTION + [_vinyl(1965832, "The Birthday Party", "Prayers On Fire")])
    client.post("/discogs/sync")
    client.post("/discogs/import/confirm")
    assert 'id="gone"' not in client.get("/discogs/").text


def test_sync_brings_the_format_of_linked_albums_up_to_date_and_an_export_does_not(app, client):
    client.post("/discogs/token", data={"token": "secret"})
    _import(client)
    album = _store(app).load(Album)[0]
    assert (album.format_tokens.qualifiers, album.computed_width_cm) == (("LP", "Album"), 0.5)
    heavy = _vinyl(1874289, "Tom Waits", "Closing Time")
    heavy["basic_information"]["formats"][0].update(qty="2", text="Blue, Gatefold, 180g")
    app.config["DISCOGS_CLIENT_FACTORY"] = type("Heavy", (_Client,), {"collection": lambda self: [heavy]})

    preview = client.post("/discogs/sync", follow_redirects=True)
    assert "1 linked album gets its format" in preview.text
    assert _store(app).load(Album)[0].computed_width_cm == 0.5
    client.post("/discogs/import/confirm")

    album = _store(app).load(Album)[0]
    assert album.format_tokens.qualifiers == ("2xLP", "Album", "180", "Gat")
    assert album.computed_width_cm == 1.5

    # The export knows less; importing it again does not undo the sync.
    _import(client)
    assert _store(app).load(Album)[0].computed_width_cm == 1.5


def test_sync_reports_when_discogs_cannot_be_reached(app, client):
    class Unreachable(_Client):
        def collection(self):
            raise DiscogsError("Discogs could not be reached: timed out")

    app.config["DISCOGS_CLIENT_FACTORY"] = Unreachable
    client.post("/discogs/token", data={"token": "secret"})

    response = client.post("/discogs/sync")

    assert response.status_code == 502
    assert "Discogs could not be reached" in response.text


def test_an_album_that_left_discogs_is_only_removed_after_confirming(app, client):
    client.post("/discogs/token", data={"token": "secret"})
    client.post("/discogs/sync")
    client.post("/discogs/import/confirm")
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
        "Sold", (_Client,), {"collection": lambda self: COLLECTION[:1]}
    )
    client.post("/discogs/sync")
    client.post("/discogs/import/confirm")

    # An album that is still in the collection cannot be removed this way.
    assert client.post("/discogs/gone/1/remove").status_code == 302
    assert len(_store(app).load(Album)) == 3

    assert "/discogs/gone/3/remove" in client.get("/discogs/").text
    question = client.get("/discogs/gone/3/remove").text
    assert "Remove this album?" in question and "Prayers On Fire" in question
    assert "Kast · a" in question
    # Asking changes nothing, and neither does another sync: the question returns.
    client.post("/discogs/sync")
    client.post("/discogs/import/confirm")
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


def test_a_sync_and_a_fetch_bring_the_picture_of_an_artist(app, client):
    class Pictured(_Client):
        def collection(self):
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
    client.post("/discogs/sync")
    client.post("/discogs/import/confirm")

    # The sync names the artist on Discogs; the picture itself still has to be fetched.
    assert [a.discogs_artist_id for a in _store(app).load(Artist)] == [82294, None]
    waiting = client.get("/discogs/").text
    assert "The picture of 1 artist still has to be fetched." in waiting
    # Not done while a picture is open, and the artist no sync could name is accounted for.
    assert "Everything has been fetched." not in waiting and "0 of 1 artists" in waiting
    assert "1 artist is not named on Discogs" in waiting
    assert "tw150.jpeg" not in client.get("/artists/1").text
    assert "ss-cover" not in client.get("/artists/").text

    client.post("/discogs/enrich/start")
    app.extensions["enrichment_job"].wait(10)

    page = client.get("/artists/1").text
    # Fetched, the picture is shown from the data directory, not from Discogs any more.
    thumb = cover_name("https://i.discogs.com/tw150.jpeg")
    large = cover_name("https://i.discogs.com/tw.jpeg")
    assert f'src="/covers/artists/{thumb}"' in page and "Show the picture larger" in page
    assert f'data-src="/covers/artists/{large}"' in page
    assert "i.discogs.com/tw" not in page
    assert client.get(f"/covers/artists/{thumb}").data == b"jpeg"
    done = client.get("/discogs/").text
    assert "still has to be fetched" not in done
    assert "Everything has been fetched." in done and "1 of 1 artists" in done
    # An artist without a picture has the page as it was.
    assert "ss-cover-zoom" not in client.get("/artists/2").text
    # In the list the pictured artist shows its picture, and the other keeps the space.
    listed = client.get("/artists/").text
    assert f'src="/covers/artists/{thumb}"' in listed and "ss-cover-empty" in listed


def test_an_album_that_left_discogs_can_be_kept_without_being_asked_again(app, client):
    client.post("/discogs/token", data={"token": "secret"})
    client.post("/discogs/sync")
    client.post("/discogs/import/confirm")
    app.config["DISCOGS_CLIENT_FACTORY"] = type(
        "Sold", (_Client,), {"collection": lambda self: COLLECTION[:1]}
    )
    client.post("/discogs/sync")
    client.post("/discogs/import/confirm")
    assert "/discogs/gone/3/remove" in client.get("/discogs/").text

    assert client.post("/discogs/gone/3/keep").status_code == 302

    page = client.get("/discogs/").text
    assert "/discogs/gone/3/remove" not in page
    assert "Kept although not on Discogs (1)" in page and "/discogs/gone/3/ask-again" in page
    assert len(_store(app).load(Album)) == 3
    # The next sync does not ask again.
    preview = client.post("/discogs/sync", follow_redirects=True).text
    client.post("/discogs/import/confirm")
    assert "no longer in your Discogs collection" not in preview
    assert "/discogs/gone/3/remove" not in client.get("/discogs/").text

    # Taking it back lists the album as gone once more.
    client.post("/discogs/gone/3/ask-again")
    assert "/discogs/gone/3/remove" in client.get("/discogs/").text

    # An album that is still on Discogs cannot be marked, and one that returns loses the mark.
    client.post("/discogs/gone/1/keep")
    assert not _store(app).load(Album)[0].kept_after_discogs
    client.post("/discogs/gone/3/keep")
    app.config["DISCOGS_CLIENT_FACTORY"] = _Client
    client.post("/discogs/sync")
    client.post("/discogs/import/confirm")
    album = _store(app).load(Album)[2]
    assert (album.left_discogs, album.kept_after_discogs) == (False, False)


def test_a_match_confirmed_after_a_sync_brings_the_cover_of_its_release(app, client):
    class Renamed(_Client):
        def collection(self):
            # The release is titled a little differently than the album was loaded.
            return [_vinyl(1874289, "Tom Waits", "Closing Time (Remastered)")]

    app.config["DISCOGS_CLIENT_FACTORY"] = Renamed
    client.post("/discogs/token", data={"token": "secret"})
    client.post("/discogs/sync")
    client.post("/discogs/import/confirm")

    # Not the same title, so the link waits for a yes — and the album has no release yet.
    album = _store(app).load(Album)[0]
    assert (album.release_id, album.cover_url) == (None, None)
    assert "1</div>" in client.get("/discogs/").text

    client.post("/discogs/matches/1/accept")

    album = _store(app).load(Album)[0]
    assert album.release_id == 1874289
    assert album.cover_url == "https://i.discogs.com/1874289.jpeg"
    assert album.cover_image_url == "https://i.discogs.com/1874289-large.jpeg"


def test_the_screen_marks_the_step_that_waits_and_leads_on_to_the_next(app, client):
    class Renamed(_Client):
        def collection(self):
            return [_vinyl(1874289, "Tom Waits", "Closing Time (Remastered)")]

    app.config["DISCOGS_CLIENT_FACTORY"] = Renamed
    # Without a token that is the thing to do, and the token block stands open.
    page = client.get("/discogs/").text
    assert "needed first" in page and '<details class="ss-card mt-4" id="token-block" open>' in page
    client.post("/discogs/token", data={"token": "secret"})
    page = client.get("/discogs/").text
    assert "set: ••••cret" in page and 'id="token-block" >' in page
    # The steps stand in the order they are done: sync, matches, fetch.
    assert page.index('id="sync"') < page.index('id="matches"') < page.index('id="enrich"')

    # A sync shows what it would do inside the first step, which is then the one that waits.
    synced = client.post("/discogs/sync")
    assert synced.headers["Location"] == "/discogs/#sync"
    page = client.get("/discogs/").text
    assert "ss-step-current\" id=\"sync\"" in page and "to take over" in page
    assert "Take over" in page and ">Sync</button>" not in page

    # Taking it over leads to the matches, which wait next; confirming them to the fetching.
    taken = client.post("/discogs/import/confirm")
    assert taken.headers["Location"] == "/discogs/#matches"
    page = client.get("/discogs/").text
    assert "ss-step-current\" id=\"matches\"" in page and "1 to confirm" in page
    client.post("/discogs/matches/1/accept")
    page = client.get("/discogs/").text
    assert "ss-step-current\" id=\"enrich\"" in page and "ss-step-current\" id=\"matches\"" not in page

    client.post("/discogs/enrich/start")
    app.extensions["enrichment_job"].wait(10)
    assert "ss-step-current" not in client.get("/discogs/").text


def test_a_sync_that_was_fetched_can_be_discarded(app, client):
    client.post("/discogs/token", data={"token": "secret"})
    client.post("/discogs/sync")
    assert "Nothing has changed yet." in client.get("/discogs/").text

    discarded = client.post("/discogs/import/discard")

    assert discarded.headers["Location"] == "/discogs/#sync"
    page = client.get("/discogs/").text
    assert "Nothing has changed yet." not in page and ">Sync</button>" in page
    assert all(album.release_id is None for album in _store(app).load(Album))
