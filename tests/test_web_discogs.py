"""Tests for the Discogs screen: import, enrichment job, and match confirmation."""

import io
from datetime import datetime

import pytest

from sleeve_shelf import create_app
from sleeve_shelf.config import load_settings
from sleeve_shelf.domain import (
    Album,
    Artist,
    MasterEnrichment,
    MatchProposal,
    ReleaseEnrichment,
)
from sleeve_shelf.persistence import JsonStore

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
        "/discogs/import", data={"export": (io.BytesIO(EXPORT.encode()), "collection.csv")}
    )
    assert preview.status_code == 200
    assert client.post("/discogs/import/confirm").status_code == 302
    return preview


def test_import_previews_and_only_changes_things_on_confirm(app, client):
    preview = client.post(
        "/discogs/import", data={"export": (io.BytesIO(EXPORT.encode()), "collection.csv")}
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
    album = _store(app).load(Album)[0]
    assert (album.master_id, album.original_release_year) == (77, 1973)
    page = client.get("/discogs/").text
    assert "Enrichment finished." in page and "Every linked album has been fetched." in page


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
