"""Tests for the web layer: first-use wizard, Browse/Search, and unplaced albums."""

import io

import pytest
from openpyxl import Workbook

from sleeve_shelf import create_app, main
from sleeve_shelf.domain import Album, Shelf
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
    for screen in ("/browse", "/unplaced", "/albums/1", "/artists/", "/clusters/", "/dashboard/",
                   "/layout/", "/proposal/", "/showcase/", "/versions/"):
        assert client.get(screen).headers.get("Location") == "/setup/", screen
    # What can be set up before there is a collection stays open.
    for screen in ("/storage/", "/discogs/", "/families/", "/rules/", "/settings/"):
        assert client.get(screen).status_code == 200, screen
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

    assert "No artist, album or song matches" in client.get("/browse?q=zappa").text


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
    # Nothing has a type, row, reachability or showcase yet: those columns are left out.
    assert all(f">{name}</th>" not in page for name in ("Type", "Row", "Reachability", "Showcase"))


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
    # Once one shelf has them, the columns are there.
    assert ">Row</th>" in page and ">Showcase</th>" in page
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
    assert "Suggested families (2)" in page and "Chet Baker Quartet" in page

    client.post("/families/suggestions/3/dismiss")
    client.post("/families/suggestions/1/accept", data={"member": "2"})

    page = client.get("/families/").text
    assert "Suggested families (0)" in page
    assert "Families (1)" in page and 'value="Chet Baker"' in page


def test_discogs_membership_suggests_families_and_additions_to_them(client):
    from datetime import datetime

    from sleeve_shelf.domain import Artist, ArtistEnrichment

    _load(client, layout=[
        ["Kast", "a", "Rock", "1980s", "Nick Cave", "Solo", 1984],
        ["Kast", "a", "Rock", "1980s", "Grinderman", "Grinderman", 2007],
        ["Kast", "a", "Rock", "1980s", "The Birthday Party", "Junkyard", 1982],
        ["Kast", "a", "Rock", "1980s", "The Boys Next Door", "Door, Door", 1979],
    ])
    store = JsonStore(client.application.config["DATA_DIR"])
    artists = store.load(Artist)
    ids = {artist.name: artist.id for artist in artists}
    for artist in artists:
        artist.discogs_artist_id = 100 + artist.id
    store.save(Artist, artists)
    now = datetime(2026, 10, 12)
    cave, grinderman = ids["Nick Cave"], ids["Grinderman"]
    store.save(ArtistEnrichment, [
        ArtistEnrichment(100 + cave, None, None, now, (), (100 + grinderman,), ()),
        ArtistEnrichment(100 + ids["The Birthday Party"], None, None, now, (100 + cave,), (), ()),
        ArtistEnrichment(100 + ids["The Boys Next Door"], None, None, now, (100 + cave,), (), ()),
    ])

    page = client.get("/families/").text
    assert "Suggested families (1)" in page and "Discogs lists them" in page
    client.post(
        f"/families/suggestions/{cave}/accept", data={"member": str(grinderman)}
    )

    # The two bands left unticked are now offered to the family that exists.
    page = client.get("/families/").text
    assert "Add to the family “Nick Cave”" in page and "Suggested families (1)" in page
    anchor = min(cave, grinderman)
    client.post(
        f"/families/suggestions/{anchor}/accept", data={"member": str(ids["The Birthday Party"])}
    )
    assert {a.name for a in store.load(Artist) if a.alias_group_id} == {
        "Nick Cave", "Grinderman", "The Birthday Party"
    }
    assert "Families (1)" in client.get("/families/").text

    # Turning the last one down keeps it out, without hiding later additions to the family.
    client.post(f"/families/suggestions/{anchor}/dismiss")
    assert "Suggested families (0)" in client.get("/families/").text


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


def test_menu_has_five_sections_and_tabs_that_count_what_is_waiting(client):
    _load(client, unplaced=[["Jazz", "Chet Baker", "Chet", 1]])

    page = client.get("/browse").text

    menu = page[page.index('id="main-nav"'):page.index("</nav>")]
    sections = ["Dashboard", "Collection", "Shelves", "Organise", "Settings"]
    assert [menu.index(f"<span>{name}</span>") for name in sections] == sorted(
        menu.index(f"<span>{name}</span>") for name in sections
    )
    # Five sections, and Help apart at the end.
    assert menu.count("<a ") == 6 and menu.rindex("<span>Help</span>") > menu.index("<span>Settings</span>")
    # Browse belongs to Collection: that section is marked, and its screens are the tabs.
    collection = menu[menu.rindex("<a ", 0, menu.index("<span>Collection</span>")):]
    assert 'class="active"' in collection[: collection.index("</a>")]
    # One LP has no place: Collection says so, and so does the tab it is on.
    assert 'title="Waiting for you">1</span>' in collection[: collection.index("</a>")]
    tabs = page[page.index('class="ss-section-tabs"'):]
    tabs = tabs[: tabs.index("</nav>")]
    assert ["Browse / Search" in tabs, "Unplaced" in tabs, "Discogs sync" in tabs] == [True] * 3
    unplaced = tabs[tabs.index("Unplaced"):]
    assert '<span class="ss-nav-count">1</span>' in unplaced[: unplaced.index("</a>")]
    assert 'aria-current="page"' in tabs[: tabs.index("Unplaced")]

    # The other sections show their own screens as tabs.
    assert "Cabinets" in client.get("/layout/").text.split('class="ss-section-tabs"')[1]
    assert "Rules" in client.get("/families/").text.split('class="ss-section-tabs"')[1]
    # The workbook is imported from the Discogs screen, the theme is switched in Settings.
    assert "/setup/upload" in client.get("/discogs/").text
    settings = client.get("/settings/").text
    assert "data-theme-toggle" in settings and 'class="ss-section-tabs"' not in settings


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
    # Families and artists are neither to do nor ticked off while there are no albums.
    assert dashboard.count("once there are albums") == 2
    assert "ss-step-done" not in dashboard
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
    # With albums the two steps count again.
    assert "once there are albums" not in client.get("/dashboard/").text
    unplaced = client.get("/unplaced").text
    assert "Bleach" in unplaced and "Nevermind" in unplaced

    client.post("/proposal/generate")
    assert "Do not fit (0)" in client.get("/proposal/").text
    client.post("/proposal/accept")

    shelf = client.get("/browse").text
    assert "Bleach" in shelf and "Nevermind" in shelf and "Lithium" not in shelf
    assert "Saved versions (1)" in client.get("/versions/").text


def test_every_menu_section_has_its_icon(client):
    from pathlib import Path

    from sleeve_shelf.web.navigation import SECTIONS

    _load(client)
    sprite = (Path(client.application.static_folder) / "vendor" / "menu-icons.svg").read_text()
    menu = client.get("/browse").text
    for section in SECTIONS:
        assert f'<symbol id="{section.key}"' in sprite, section.key
        assert f'vendor/menu-icons.svg#{section.key}"' in menu, section.key
    assert client.get("/static/vendor/menu-icons.svg").status_code == 200


def test_only_a_measured_shelf_is_marked_as_too_full(client):
    _load(client)
    store = JsonStore(client.application.config["DATA_DIR"])
    albums = store.load(Album)
    for album in albums:
        album.manual_width_cm = 1.0
    store.save(Album, albums)
    # Shelf a holds two albums; a narrow width makes it too full, first as an estimate.
    client.post("/storage/shelves/1", data={"name": "a", "width_cm": "0,5", "type": "", "layer": ""})

    page = client.get("/storage/").text
    assert "&asymp; 0.5 cm" in page and "ss-over-estimate" in page and 'class="text-end ss-over"' not in page
    assert client.get("/dashboard/").text.count("filled beyond") == 0
    assert 'data-measured="0"' in client.get("/layout/").text

    client.post("/storage/shelves/1", data={"name": "a", "width_cm": "0,5", "type": "", "layer": "",
                                            "width_measured": "on"})
    page = client.get("/storage/").text
    assert "&asymp;" not in page.split("<tbody>")[1].split("</tbody>")[0]
    assert 'class="text-end ss-over"' in page
    assert "1 shelf filled beyond its measured width" in client.get("/dashboard/").text
    assert next(s for s in store.load(Shelf) if s.id == 1).width_measured is True
    # A new shelf is taken to be measured unless unticked.
    assert 'name="width_measured" checked' in client.get("/storage/cabinets/1/shelves/new").text


def test_the_search_fields_search_while_typing(client):
    _load(client)

    for page in ("/browse", "/browse?q=tinder", "/artists/"):
        text = client.get(page).text
        assert 'role="search" data-live-search' in text, page
        assert "/static/live-search.js" in text
        assert "/static/tabs.js" in text
    assert client.get("/static/live-search.js").status_code == 200


def test_the_waiting_counts_are_kept_until_something_changes(client):
    from sleeve_shelf.web.waiting import waiting_counts

    _load(client, unplaced=[["Jazz", "Chet Baker", "Chet", 1]])
    store = JsonStore(client.application.config["DATA_DIR"])

    assert waiting_counts(store)["unplaced"] == 1
    assert waiting_counts(store) == waiting_counts(store)
    # Putting the album on a shelf changes the files, and the count follows.
    album_id = next(a.id for a in store.load(Album) if a.title == "Chet")
    client.post("/move/", data={"kind": "album", "id": str(album_id), "how": "end", "shelf": "1"})
    assert waiting_counts(store)["unplaced"] == 0


def test_layout_offers_a_jump_to_every_cabinet(client):
    _load(client)
    assert 'id="jump"' not in client.get("/layout/").text

    client.post("/storage/cabinets/new", data={"name": "Koffer", "location": "Zolder"})
    client.post("/storage/cabinets/2/shelves/new", data={"name": "x", "type": "", "layer": ""})
    page = client.get("/layout/").text

    assert 'id="jump"' in page and 'id="cabinet-1"' in page
    # A cabinet in another room is reached through that room's tab.
    assert '<option value="2">' in page
    assert client.get("/layout/go?to=2").headers["Location"] == "/layout/?room=Zolder#cabinet-2"



def test_the_artist_list_goes_letter_by_letter_unless_searching(client):
    from sleeve_shelf.web.artists import initial

    assert [initial(n) for n in ("ABBA", "'Baby Face' Willette", "16 Horsepower", "Émilie Simon", "Chet Baker (2)")] == [
        "A", "B", "#", "E", "C"]
    _load(client)

    page = client.get("/artists/").text
    # The first letter with artists is shown, and letters without any are not links.
    assert 'aria-current="page">M</a>' in page and "Miles Davis" in page and "Tindersticks" not in page
    assert '<span>Q</span>' in page
    assert "Tindersticks" in client.get("/artists/?letter=T").text
    # A letter without artists falls back to the first one.
    assert "Miles Davis" in client.get("/artists/?letter=Q").text
    # Searching looks through everyone, without the letters.
    searched = client.get("/artists/?q=i").text
    assert "Miles Davis" in searched and "Tindersticks" in searched and "ss-letters" not in searched


def test_accept_all_asks_first_and_notices_are_shown_once(client):
    _load(client, layout=FAMILY_LAYOUT)

    page = client.get("/families/").text
    # The button opens a question with the number in it; the form behind it does the work.
    assert '<details class="ss-confirm">' in page and "Make 2 families" in page
    client.post("/families/suggestions/accept-all")
    assert "Families (2)" in client.get("/families/").text
    # A notice comes with the address and is taken out of it once the page is shown.
    assert "/static/notices.js" in client.get("/settings/?saved=1").text
    assert client.get("/static/notices.js").status_code == 200


def test_a_format_names_each_term_once(client):
    from sleeve_shelf.domain import FormatTokens

    _load(client)
    store = JsonStore(client.application.config["DATA_DIR"])
    albums = store.load(Album)
    albums[0].format_tokens = FormatTokens(disc_count=2, is_compound=True, qualifiers=("LP", "Album", "RE", "LP", "Album", "RE"))
    store.save(Album, albums)

    assert "LP, Album, RE</span>" in client.get(f"/albums/{albums[0].id}").text


def test_a_joint_billing_can_be_moved_or_put_with_another_artist_it_names(tmp_path):
    from sleeve_shelf.domain import Album, AliasGroup, Artist

    client = create_app(tmp_path / "data").test_client()
    client.post("/setup/start")
    store = JsonStore(tmp_path / "data")
    store.save(AliasGroup, [AliasGroup(1, "Chick Webb And His Orchestra"), AliasGroup(2, "Ella Fitzgerald")])
    store.save(
        Artist,
        [Artist(1, "Chick Webb And His Orchestra", alias_group_id=1),
         Artist(2, "Chick Webb And His Orchestra Featuring Ella Fitzgerald", alias_group_id=1),
         Artist(3, "Ella Fitzgerald", alias_group_id=2),
         Artist(4, "Lou Reed"), Artist(5, "The Velvet Underground"),
         Artist(6, "The Velvet Underground With Lou Reed")],
    )
    store.save(
        Album,
        [Album(1, 1, "Stompin' At The Savoy"), Album(2, 2, "A-Tisket, A-Tasket"),
         Album(3, 3, "Ella Sings Gershwin"), Album(4, 3, "Lullabies Of Birdland"),
         Album(5, 4, "Transformer"), Album(6, 4, "Berlin"), Album(7, 6, "Live 1969")],
    )

    page = client.get("/families/").text
    assert "Moves out of the family “Chick Webb And His Orchestra”." in page
    assert "Also names The Velvet Underground" in page

    # Accepting the move puts the album with Ella.
    client.post("/families/suggestions/3/accept", data={"member": "2", "source": "names"})
    assert next(a for a in JsonStore(tmp_path / "data").load(Artist) if a.id == 2).alias_group_id == 2
    # The joint billing goes with the band rather than with the artist the rule chose.
    client.post("/families/members/6/with/5")
    artists = {a.id: a for a in JsonStore(tmp_path / "data").load(Artist)}
    assert artists[6].alias_group_id == artists[5].alias_group_id is not None
    assert artists[4].alias_group_id is None


def test_putting_back_a_version_that_does_not_exist_is_refused(client):
    _load(client)
    assert client.post("/versions/20990101-000000/restore").status_code == 404
    assert client.post("/versions/..%2Fplacement_current/restore").status_code == 404
