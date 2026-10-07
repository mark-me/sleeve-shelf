"""Tests for the web layer: first-use wizard, Browse/Search, and unplaced albums."""

import io

import pytest
from openpyxl import Workbook

from sleeve_shelf import create_app


def _workbook(layout_rows, unplaced=()) -> io.BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Kastindeling"
    sheet.append(
        ["Locatie", "Vak", "Cluster", "Era-band (artiest)", "Artiest", "Titel", "Sorteerjaar (origineel)"]
    )
    for row in layout_rows:
        sheet.append(row)
    sheet = workbook.create_sheet("Nog niet geplaatst")
    sheet.append(["Cluster", "Artiest", "Titel", "Aantal schijven"])
    for row in unplaced:
        sheet.append(row)
    content = io.BytesIO()
    workbook.save(content)
    content.seek(0)
    return content


LAYOUT = [
    ["Kast", "a", "Slowcore", "1990s", "Tindersticks", "Nénette Et Boni", 1996],
    ["Kast", "a", "Slowcore", "1990s", "Tindersticks", "Curtains", 1997],
    ["Kast", "b", "Jazz", "voor 1960", "Miles Davis", "Kind Of Blue", 1959],
]


@pytest.fixture
def client(tmp_path):
    return create_app(tmp_path / "data").test_client()


def _load(client, layout=LAYOUT, unplaced=()):
    preview = client.post(
        "/setup/upload", data={"workbook": (_workbook(layout, unplaced), "layout.xlsx")}
    )
    assert preview.status_code == 200
    confirmed = client.post("/setup/confirm")
    assert confirmed.status_code == 302
    return preview


def test_without_a_collection_everything_leads_to_the_wizard(client):
    assert client.get("/").headers["Location"] == "/setup/"
    assert client.get("/browse").headers["Location"] == "/setup/"
    assert client.get("/setup/").status_code == 200
    assert client.get("/setup/upload").status_code == 200


def test_upload_previews_before_loading(client):
    preview = client.post(
        "/setup/upload", data={"workbook": (_workbook(LAYOUT), "layout.xlsx")}
    )

    assert "2 albums" in preview.text and "1 album" in preview.text
    assert client.get("/browse").headers["Location"] == "/setup/"

    assert client.post("/setup/confirm").headers["Location"] == "/browse"
    assert client.get("/").headers["Location"] == "/browse"


def test_browse_shows_a_shelf_in_row_order_with_neighbours(client):
    _load(client)

    first = client.get("/browse").text
    assert first.index("Nénette Et Boni") < first.index("Curtains")
    assert "Slowcore · 1990s" in first
    assert "Kind Of Blue" not in first
    assert "/browse?shelf=2" in first

    second = client.get("/browse?shelf=2").text
    assert "Kind Of Blue" in second and "1959" in second
    assert "/browse?shelf=1" in second


def test_search_ignores_case_and_accents_and_links_to_the_shelf(client):
    _load(client, unplaced=[["Jazz", "Miles Davis", "Sketches Of Spain", 1]])

    results = client.get("/browse?q=nenette+TINDER").text
    assert "1 result for" in results
    assert "/browse?shelf=1#album-1" in results

    miles = client.get("/browse?q=miles").text
    assert "2 results for" in miles
    assert "/unplaced#album-4" in miles

    assert "No artist or album matches" in client.get("/browse?q=zappa").text


def test_unplaced_albums_are_listed(client):
    _load(client, unplaced=[["Jazz", "Miles Davis", "Sketches Of Spain", 1]])

    assert "Sketches Of Spain" in client.get("/unplaced").text


def test_a_new_upload_replaces_everything(client):
    _load(client)
    _load(client, layout=[["Koffer", "x", "Rock", "1970s", "Tom Waits", "Closing Time", 1973]])

    page = client.get("/browse").text
    assert "Closing Time" in page
    assert "Tindersticks" not in page and "Kast" not in page
    assert "No artist or album matches" in client.get("/browse?q=miles").text


def test_unreadable_upload_is_reported_and_nothing_is_loaded(client):
    response = client.post(
        "/setup/upload", data={"workbook": (io.BytesIO(b"not a workbook"), "layout.xlsx")}
    )

    assert response.status_code == 400
    assert "could not be read" in response.text
    assert client.post("/setup/confirm").headers["Location"] == "/setup/upload"


def test_cross_site_posts_are_rejected(client):
    response = client.post("/setup/confirm", headers={"Sec-Fetch-Site": "cross-site"})

    assert response.status_code == 403
