"""Tests for the web layer: first-use wizard, Browse/Search, and unplaced albums."""

import io

import pytest
from openpyxl import Workbook

from sleeve_shelf import create_app, main
from sleeve_shelf.domain import Album
from sleeve_shelf.persistence import JsonStore


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
    assert client.get("/").headers["Location"] == "/dashboard/"


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


def test_a_new_upload_only_changes_the_layout(client):
    _load(client)
    client.post("/storage/shelves/1", data={"name": "a", "width_cm": "42", "type": "", "layer": ""})
    client.post("/families/new", data={"label": "Stuart Staples"})
    client.post("/families/1/members", data={"artist": "Tindersticks"})

    _load(
        client,
        layout=[
            ["Kast", "b", "Slowcore", "1990s", "Tindersticks", "Curtains", 1997],
            ["Kast", "b", "Jazz", "voor 1960", "Miles Davis", "Kind Of Blue", 1959],
            ["Koffer", "x", "Rock", "1970s", "Tom Waits", "Closing Time", 1973],
        ],
    )

    # Albums moved to where the new workbook has them; a new album and cabinet were added.
    shelf_b = client.get("/browse?shelf=2").text
    assert shelf_b.index("Curtains") < shelf_b.index("Kind Of Blue")
    assert "Closing Time" in client.get("/browse?shelf=3").text
    # The album the workbook no longer lists is kept, without a place.
    assert "Nénette Et Boni" in client.get("/unplaced").text
    assert "/unplaced#album-1" in client.get("/browse?q=nenette").text
    # What was set by hand survives: the shelf width and the family.
    assert "42.0 cm" in client.get("/storage/").text
    families = client.get("/families/").text
    assert 'value="Stuart Staples"' in families and "/families/members/1/remove" in families


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


def test_workbook_can_be_loaded_from_the_command_line(tmp_path, monkeypatch, capsys):
    workbook = tmp_path / "layout.xlsx"
    workbook.write_bytes(_workbook(LAYOUT).getvalue())
    monkeypatch.setenv("SLEEVE_SHELF_DATA_DIR", str(tmp_path / "data"))

    main(["load", str(workbook)])

    assert "Loaded 3 albums on 2 shelves" in capsys.readouterr().out
    assert "Kind Of Blue" in create_app().test_client().get("/browse?shelf=2").text


def test_storage_lists_cabinets_with_how_full_each_shelf_is(client):
    _load(client)

    page = client.get("/storage/").text

    assert "Kast" in page
    assert "/storage/shelves/1" in page and "/storage/shelves/2" in page
    # A shelf holding albums cannot be removed.
    assert "/storage/shelves/1/delete" not in page


def test_cabinets_and_shelves_can_be_added_edited_and_removed(client):
    _load(client)

    client.post("/storage/cabinets/new", data={"name": "Koffer", "location": "Zolder"})
    assert "Zolder" in client.get("/storage/").text

    created = client.post(
        "/storage/cabinets/2/shelves/new",
        data={"name": "links", "width_cm": "38,5", "type": "top_loader", "layer": "top",
              "reachability_score": "1", "is_showcase": "on"},
    )
    assert created.status_code == 302
    page = client.get("/storage/").text
    assert "38.5 cm" in page and "Top-loader" in page
    # The new, empty shelf shows up in Browse as a stop.
    assert "Koffer &rsaquo; links (0)" in client.get("/browse").text

    client.post("/storage/shelves/3", data={"name": "rechts", "width_cm": "", "type": "", "layer": ""})
    form = client.get("/storage/shelves/3").text
    assert 'value="rechts"' in form

    # A cabinet with shelves stays; once the shelf is gone it can go too.
    client.post("/storage/cabinets/2/delete")
    assert "Koffer" in client.get("/storage/").text
    client.post("/storage/shelves/3/delete")
    client.post("/storage/cabinets/2/delete")
    assert "Koffer" not in client.get("/storage/").text


def test_shelf_input_is_validated(client):
    _load(client)

    response = client.post(
        "/storage/shelves/1",
        data={"name": "", "width_cm": "wide", "type": "front_loader", "reachability_score": "1.5",
              "is_showcase": "on"},
    )

    assert response.status_code == 400
    for message in ("Give the shelf a name", "The width has to be", "Reachability has to be",
                    "Only a top-loader"):
        assert message in response.text
    assert 'value="wide"' in response.text


def test_a_shelf_holding_albums_cannot_be_removed(client):
    _load(client)

    response = client.post("/storage/shelves/1/delete", follow_redirects=True)

    assert "still holds albums" in response.text
    assert "Nénette Et Boni" in client.get("/browse?shelf=1").text
    assert client.get("/storage/shelves/99").status_code == 404


FAMILY_LAYOUT = [
    ["Kast", "a", "Jazz", "voor 1960", "Chet Baker", "Chet", 1959],
    ["Kast", "a", "Jazz", "voor 1960", "Chet Baker Quartet", "Quartet", 1955],
    ["Kast", "a", "Rock", "1990s", "Rex", "One", 1996],
    ["Kast", "a", "Rock", "1970s", "T. Rex", "Electric Warrior", 1971],
]


def test_family_suggestions_can_be_accepted_or_turned_down(client):
    _load(client, layout=FAMILY_LAYOUT)

    page = client.get("/families/").text
    assert "Suggested from the names (2)" in page and "Chet Baker Quartet" in page

    client.post("/families/suggestions/3/dismiss")
    client.post("/families/suggestions/1/accept", data={"member": "2"})

    page = client.get("/families/").text
    assert "Suggested from the names (0)" in page
    assert "Families (1)" in page and 'value="Chet Baker"' in page


def test_a_family_can_be_made_and_changed_by_hand(client):
    _load(client, layout=FAMILY_LAYOUT)
    client.post("/families/suggestions/1/dismiss")
    client.post("/families/suggestions/3/dismiss")

    client.post("/families/new", data={"label": "Glam"})
    client.post("/families/1/members", data={"artist": "t. rex"})
    assert "Choose an artist from the list." in client.post(
        "/families/1/members", data={"artist": "Nobody"}, follow_redirects=True
    ).text
    client.post("/families/1/rename", data={"label": "Marc Bolan"})

    page = client.get("/families/").text
    assert 'value="Marc Bolan"' in page and "/families/members/4/remove" in page

    client.post("/families/members/4/remove")
    assert "No artists in this family yet." in client.get("/families/").text
    client.post("/families/1/delete")
    assert "Families (0)" in client.get("/families/").text


def test_unplaced_singles_are_listed_apart_from_lps(client, tmp_path):
    _load(client)
    export = (
        "Catalog#,Artist,Title,Label,Format,Rating,Released,release_id\n"
        'A,Nirvana,Lithium,DGC,"12"", Ltd, Pic",,1992,505982\n'
        'B,Nirvana,Bleach,Sub Pop,"LP, Album",,2009,4275916\n'
    )
    client.post("/discogs/import", data={"export": (io.BytesIO(export.encode()), "c.csv")})
    client.post("/discogs/import/confirm")

    page = client.get("/unplaced").text

    assert "Singles and EPs (1)" in page
    assert page.index("Bleach") < page.index("Singles and EPs") < page.index("Lithium")


def test_cabinets_and_shelves_can_be_put_in_order(client):
    _load(client)
    client.post("/storage/cabinets/new", data={"name": "Koffer"})
    client.post("/storage/cabinets/2/shelves/new", data={"name": "x", "type": "", "layer": ""})

    def stops():
        page = client.get("/browse").text
        return [page.index(label) for label in ("Kast &rsaquo; a", "Kast &rsaquo; b", "Koffer &rsaquo; x")]

    a, b, x = stops()
    assert a < b < x

    client.post("/storage/cabinets/2/move", data={"direction": "up"})
    client.post("/storage/shelves/2/move", data={"direction": "up"})

    a, b, x = stops()
    assert x < b < a
    # Browse now starts at the first shelf in that order that holds anything.
    assert "Kind Of Blue" in client.get("/browse").text
    storage = client.get("/storage/").text
    assert storage.index("Koffer") < storage.index("Kast")

    # Moving past the end changes nothing.
    client.post("/storage/cabinets/2/move", data={"direction": "up"})
    assert stops() == [a, b, x]


def test_covers_show_in_browse_search_and_layout_once_albums_have_them(client):
    _load(client)
    assert "ss-cover" not in client.get("/browse").text

    store = JsonStore(client.application.config["DATA_DIR"])
    albums = store.load(Album)
    albums[0].cover_url = "https://i.discogs.com/nenette.jpeg"
    store.save(Album, albums)

    shelf = client.get("/browse").text
    assert '<img class="ss-cover" src="https://i.discogs.com/nenette.jpeg"' in shelf
    # The album without a cover keeps the space, so the rows line up.
    assert shelf.count("ss-cover-empty") == 1
    assert "nenette.jpeg" in client.get("/browse?q=tindersticks").text
    assert "ss-cover" not in client.get("/browse?q=miles").text
    layout = client.get("/layout/").text
    assert layout.count('<img class="ss-cover"') == 1
    assert 'data-covers="https://i.discogs.com/nenette.jpeg|"' in layout
    artist = client.get("/artists/1").text
    assert "nenette.jpeg" in artist and "ss-cover-empty" in artist


def test_menu_is_grouped_and_counts_what_is_waiting(client):
    _load(client, unplaced=[["Jazz", "Chet Baker", "Chet", 1]])

    page = client.get("/browse").text

    groups = [page.index(f'<div class="ss-nav-group">{name}</div>') for name in ("Collection", "Arrange", "Sorting rules", "Setup")]
    assert groups == sorted(groups)
    assert page.index("Sorting proposal") < groups[2] < page.index("Artist families") < groups[3]
    assert "Cabinets & shelves" in page and "Discogs sync" in page and "Import workbook" in page
    # One LP has no place: the menu says so behind Unplaced albums.
    unplaced = page[page.index("<span>Unplaced albums</span>"):]
    unplaced = unplaced[: unplaced.index("</a>")]
    assert 'class="ss-nav-count" title="Waiting for you">1</span>' in unplaced
    # Nothing waits under Discogs sync, so it shows no number.
    discogs = page[page.index("<span>Discogs sync</span>"):]
    assert "ss-nav-count" not in discogs[: discogs.index("</a>")]


def test_app_can_be_installed_from_its_manifest(client):
    manifest = client.get("/manifest.webmanifest")

    assert manifest.mimetype == "application/manifest+json"
    data = manifest.get_json()
    assert (data["display"], data["start_url"], data["scope"]) == ("standalone", "/browse", "/")
    assert {icon["sizes"] for icon in data["icons"]} == {"192x192", "512x512"}
    assert any(icon["purpose"] == "maskable" for icon in data["icons"])
    # Every icon the manifest and the page name is really there.
    for icon in data["icons"]:
        assert client.get(icon["src"]).status_code == 200
    page = client.get("/setup/").text
    assert 'rel="manifest" href="/manifest.webmanifest"' in page
    assert client.get("/static/icons/apple-touch-icon.png").status_code == 200


def test_a_collection_can_be_started_without_a_workbook(client):
    welcome = client.get("/setup/").text
    assert "Start without a workbook" in welcome

    assert client.post("/setup/start").headers["Location"] == "/dashboard/"

    # Every screen opens on an empty collection.
    for url in ("/dashboard/", "/browse", "/unplaced", "/layout/", "/proposal/", "/artists/",
                "/clusters/", "/families/", "/rules/", "/storage/", "/discogs/", "/versions/",
                "/settings/", "/albums/widths", "/setup/upload"):
        assert client.get(url).status_code == 200, url
    dashboard = client.get("/dashboard/").text
    # Taking over the collection and entering shelves are both still to do.
    assert dashboard.count("1 to do") == 2
    assert "Add your cabinets and shelves" in client.get("/browse").text


def test_from_discogs_to_an_accepted_layout_without_a_workbook(client):
    client.post("/setup/start")
    client.post("/storage/cabinets/new", data={"name": "Kast", "location": "Kamer"})
    client.post("/storage/cabinets/1/shelves/new",
                data={"name": "a", "width_cm": "10", "type": "", "layer": ""})
    export = (
        "Catalog#,Artist,Title,Label,Format,Rating,Released,release_id\n"
        'A,Nirvana,Bleach,Sub Pop,"LP, Album",,2009,4275916\n'
        'B,Nirvana,Nevermind,DGC,"LP, Album",,2017,10859343\n'
        'C,Nirvana,Lithium,DGC,"12"", Ltd, Pic",,1992,505982\n'
    )
    client.post("/discogs/import", data={"export": (io.BytesIO(export.encode()), "c.csv")})
    client.post("/discogs/import/confirm")

    for url in ("/dashboard/", "/browse", "/unplaced", "/layout/", "/storage/", "/artists/"):
        assert client.get(url).status_code == 200, url
    unplaced = client.get("/unplaced").text
    assert "Bleach" in unplaced and "Nevermind" in unplaced

    client.post("/proposal/generate")
    assert "Do not fit (0)" in client.get("/proposal/").text
    client.post("/proposal/accept")

    shelf = client.get("/browse").text
    assert "Bleach" in shelf and "Nevermind" in shelf and "Lithium" not in shelf
    assert "Saved versions (1)" in client.get("/versions/").text
