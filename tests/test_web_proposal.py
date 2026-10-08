"""Tests for the sorting proposal: generating, browsing, accepting and discarding it."""

import io

import pytest
from openpyxl import Workbook

from sleeve_shelf import create_app
from sleeve_shelf.domain import Album
from sleeve_shelf.persistence import JsonStore

HEADER = ["Locatie", "Vak", "Cluster", "Era-band (artiest)", "Jaar artiest", "Artiest", "Titel",
          "Formaat", "Sorteerjaar (origineel)", "Jaarbron"]
# Deliberately out of order on the shelf: Rock before Jazz, late before early.
LAYOUT = [
    ["Kast", "a", "Jazz", "voor 1960", 1949, "Chet Baker", "Chet", "LP, Album", 1959, "origineel jaar (opgezocht)"],
    ["Kast", "a", "Jazz", "voor 1960", 1949, "Chet Baker", "Sings", "LP, Album", 1954, "origineel jaar (opgezocht)"],
    ["Kast", "a", "Jazz", "voor 1960", 1944, "Art Blakey", "Moanin'", "LP, Album", 1958, "origineel jaar (opgezocht)"],
    ["Kast", "b", "Rock", "1960s", 1967, "The Stooges", "Fun House", "LP, Album", 1970, "origineel jaar (opgezocht)"],
    ["Kast", "b", "Rock", "1960s", 1967, "The Stooges", "Box", "6xLP, Comp + Box", 2010, "origineel jaar (opgezocht)"],
]
SHELVES = [["Kast", "a", 3, "1"], ["Kast", "b", 3, "2"], ["Kast", "c", 3, "3"]]


@pytest.fixture
def client(tmp_path):
    client = create_app(tmp_path / "data").test_client()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Kastindeling"
    sheet.append(HEADER)
    for row in LAYOUT:
        sheet.append(row)
    sheet = workbook.create_sheet("Vakoverzicht")
    sheet.append(["Locatie", "Vak", "Capaciteit", "Toegankelijkheid"])
    for row in SHELVES:
        sheet.append(row)
    content = io.BytesIO()
    workbook.save(content)
    content.seek(0)
    client.post("/setup/upload", data={"workbook": (content, "layout.xlsx")})
    client.post("/setup/confirm")
    return client


def test_proposal_is_kept_next_to_the_layout_until_accepted(client):
    before = client.get("/browse?shelf=1").text
    assert "Generate a proposal" in client.get("/proposal/").text

    client.post("/proposal/generate")

    page = client.get("/proposal/").text
    # Each shelf is 1.5 cm wide: three LPs a shelf; the box set (3 cm) fits nowhere.
    assert "Do not fit (1)" in page and "Box" in page
    assert client.get("/browse?shelf=1").text == before

    proposed = client.get("/browse?layout=proposal&shelf=1").text
    assert "You are browsing the proposal" in proposed
    # Jazz was first on the shelves, so it stays first; within it Art Blakey, then Chet by year.
    assert proposed.index("Moanin") < proposed.index("Sings") < proposed.index("Chet &middot; 1959")
    assert "Fun House" in client.get("/browse?layout=proposal&shelf=2").text
    assert "layout=proposal" in proposed


def test_accepting_makes_the_proposal_the_layout(client):
    client.post("/proposal/generate")

    assert client.post("/proposal/accept").headers["Location"] == "/browse"

    shelf = client.get("/browse?shelf=1").text
    assert shelf.index("Moanin") < shelf.index("Sings") < shelf.index("Chet &middot; 1959")
    assert "Jazz · before 1960" in shelf
    assert "Box" in client.get("/unplaced").text
    assert "Generate a proposal" in client.get("/proposal/").text


def test_discarding_leaves_everything_as_it_was(client):
    before = client.get("/browse?shelf=1").text
    client.post("/proposal/generate")

    client.post("/proposal/discard")

    assert client.get("/browse?shelf=1").text == before
    assert "Generate a proposal" in client.get("/proposal/").text
    # Without a proposal the proposal view falls back to the real shelves.
    assert "You are browsing the proposal" not in client.get("/browse?layout=proposal").text


def test_showcase_shelves_and_shelves_without_width_are_skipped(client):
    client.post("/storage/shelves/1", data={"name": "a", "width_cm": "1.5", "type": "top_loader",
                                             "layer": "", "is_showcase": "on"})
    client.post("/storage/shelves/3", data={"name": "c", "width_cm": "", "type": "", "layer": ""})
    page = client.get("/proposal/").text
    assert "showcase" in page and "no width set" in page

    client.post("/proposal/generate")

    page = client.get("/proposal/").text
    assert "showcase, not filled" in page and "no width, not filled" in page
    # Only shelf b is left: three LPs fit, one LP and the box set do not.
    assert "Do not fit (2)" in page


def _add_new_artist(client):
    export = (
        "Catalog#,Artist,Title,Label,Format,Rating,Released,release_id\n"
        'X,New Band,Debut,Label,"LP, Album",,2021,111\n'
    )
    client.post("/discogs/import", data={"export": (io.BytesIO(export.encode()), "c.csv")})
    client.post("/discogs/import/confirm")


def test_artists_to_check_are_those_without_cluster_or_start_year(client):
    _add_new_artist(client)

    everyone = client.get("/artists/").text
    to_check = client.get("/artists/?show=attention").text

    assert "Chet Baker" in everyone and "New Band" in everyone
    assert "New Band" in to_check and "Chet Baker" not in to_check
    assert "New Band" in client.get("/artists/?q=new").text
    assert "No artist matches." in client.get("/artists/?q=zappa").text


def test_start_year_and_cluster_can_be_set_for_an_artist(client):
    _add_new_artist(client)
    page = client.get("/artists/4").text
    assert "wikipedia.org" in page and "search=new%20band" in page
    assert "Era band: unknown" in page

    bad = client.post("/artists/4", data={"start_year": "long ago", "cluster_id": ""})
    assert bad.status_code == 400 and "has to be a year" in bad.text

    client.post("/artists/4", data={"start_year": "1968", "cluster_id": "2", "new_cluster": ""})

    page = client.get("/artists/4").text
    assert "Era band: 1960s" in page and 'value="1968"' in page
    assert "New Band" not in client.get("/artists/?show=attention").text
    # The new band now sorts into Rock, in the 1960s band, after The Stooges? No: before, by name.
    client.post("/proposal/generate")
    shelf = client.get("/browse?layout=proposal&shelf=2").text
    assert shelf.index("Debut") < shelf.index("Fun House")


def test_an_artist_can_get_a_cluster_of_its_own(client):
    client.post("/artists/1", data={"start_year": "1949", "cluster_id": "1", "new_cluster": "Chet Baker"})

    page = client.get("/artists/1").text
    assert '<option value="3" selected>Chet Baker</option>' in page
    assert "Chet Baker" in client.get("/artists/?q=chet").text


def test_a_proposed_cluster_can_be_confirmed_from_the_list(client):
    _add_new_artist(client)
    from sleeve_shelf.domain import Style, Album
    from sleeve_shelf.persistence import JsonStore

    store = JsonStore(client.application.config["DATA_DIR"])
    store.save(Style, [Style(1, "Garage Rock", 2)])
    albums = store.load(Album)
    albums[-1].style_ids = [1]
    store.save(Album, albums)
    client.post("/proposal/generate")
    client.post("/proposal/accept")

    listed = client.get("/artists/?show=attention").text
    assert "proposed" in listed and "/artists/4/confirm" in listed

    client.post("/artists/4/confirm", data={"next": "/artists/?show=attention"})

    assert "/artists/4/confirm" not in client.get("/artists/?q=new").text


def test_settings_change_the_album_widths(client):
    page = client.get("/settings/").text
    assert 'value="0.5"' in page and "your albums need" in page

    bad = client.post("/settings/", data={"base_width_cm": "0", "surcharge_180_gram_cm": "x",
                                          "surcharge_gatefold_cm": "0.2"})
    assert bad.status_code == 400
    assert "above zero" in bad.text and "A surcharge has to be" in bad.text

    client.post("/settings/", data={"base_width_cm": "0,4", "surcharge_180_gram_cm": "0.1",
                                    "surcharge_gatefold_cm": "0.2", "discogs_token": "abcd1234"})

    page = client.get("/settings/").text
    assert 'value="0.4"' in page and "••••1234" in page and "abcd" not in page
    # Narrower albums: more of them fit on a 1.5 cm shelf (three at 0.5, now 0.4 each).
    client.post("/proposal/generate")
    assert "Albums proposed" in client.get("/proposal/").text
    from sleeve_shelf.domain import Album
    from sleeve_shelf.persistence import JsonStore

    albums = JsonStore(client.application.config["DATA_DIR"]).load(Album)
    assert albums[0].computed_width_cm == 0.4


def test_a_location_rule_sends_a_cluster_to_its_cabinet(client):
    client.post("/storage/cabinets/new", data={"name": "Extern"})
    client.post("/storage/cabinets/2/shelves/new", data={"name": "x", "width_cm": "5", "type": "", "layer": ""})
    assert "No rules yet" in client.get("/rules/").text

    wrong = client.post("/rules/new", data={"target_type": "cluster", "target": "Nope", "cabinet_id": "2"},
                        follow_redirects=True)
    assert "Choose a name from the list." in wrong.text
    client.post("/rules/new", data={"target_type": "cluster", "target": "rock", "cabinet_id": "2",
                                    "note": "other room"})
    client.post("/rules/new", data={"target_type": "album", "target": "Chet Baker — Sings", "cabinet_id": "2"})

    page = client.get("/rules/").text
    assert "Rules (2)" in page and "other room" in page and "Rock &rarr; Extern" in page

    client.post("/proposal/generate")

    extern = client.get("/browse?layout=proposal&shelf=4").text
    # The whole Rock cluster, box set included now that there is room, and the one Jazz album.
    assert "Fun House" in extern and "Box" in extern and "Sings" in extern
    kast = client.get("/browse?layout=proposal&shelf=1").text
    assert "Moanin" in kast and "Sings" not in kast and "Fun House" not in kast

    client.post("/rules/1/delete")
    assert "Rules (1)" in client.get("/rules/").text


def test_layout_shows_shelves_as_blocks_per_artist(client):
    page = client.get("/layout/").text

    assert 'data-shelf="1"' in page and 'data-list="0"' in page
    # Chet Baker's two albums stand together and form one block; Art Blakey is single.
    assert 'data-albums="1,2"' in page and 'data-albums="3"' in page
    # A block's name leads to its artist.
    assert 'class="ss-block-name" href="/artists/1"' in page
    assert "every move is saved at once" in page


def test_dragging_saves_the_new_contents_of_the_shelves(client):
    # Art Blakey to the front of shelf a, and Fun House from shelf b into its middle.
    moved = client.post("/layout/move", json={"shelves": {"1": [3, 4, 1, 2], "2": [5]}})

    assert moved.status_code == 200
    assert moved.get_json()["shelves"]["1"] == {"albums": 4, "filled_cm": 2.0}
    shelf = client.get("/browse?shelf=1").text
    assert shelf.index("Moanin") < shelf.index("Fun House") < shelf.index("Sings")

    # Dropping an album in the tray takes it off its shelf.
    client.post("/layout/move", json={"shelves": {"2": [], "0": [5]}})
    assert "Box" in client.get("/unplaced").text
    assert 'data-list="0"' in client.get("/layout/").text


def test_a_move_that_would_lose_or_invent_albums_is_refused(client):
    before = client.get("/browse?shelf=1").text

    for shelves in ({"1": [1, 2]}, {"1": [1, 2, 3, 99]}, {"99": [1]}, {"1": [1, 1, 2, 3]}):
        assert client.post("/layout/move", json={"shelves": shelves}).status_code == 409
    assert client.post("/layout/move", json={}).status_code == 400

    assert client.get("/browse?shelf=1").text == before


def test_the_proposal_is_adjusted_without_touching_the_shelves(client):
    client.post("/proposal/generate")
    before = client.get("/browse?shelf=1").text

    page = client.get("/layout/?layout=proposal").text
    assert "You are adjusting the proposal" in page
    moved = client.post("/layout/move?layout=proposal", json={"shelves": {"1": [1, 3, 2]}})

    assert moved.status_code == 200
    proposed = client.get("/browse?layout=proposal&shelf=1").text
    assert proposed.index("Chet &middot; 1959") < proposed.index("Moanin") < proposed.index("Sings")
    assert client.get("/browse?shelf=1").text == before


def test_a_move_by_hand_can_be_put_back_from_a_version(client):
    before = client.get("/browse?shelf=1").text
    versions = client.get("/versions/").text
    assert "Saved versions (1)" in versions and "current" in versions

    client.post("/layout/move", json={"shelves": {"1": [3, 2, 1]}})
    assert client.get("/browse?shelf=1").text != before
    page = client.get("/versions/").text
    assert "changes that are not in any version yet" in page and "/restore" in page

    import re

    name = re.search(r"/versions/([\w-]+)/restore", page).group(1)
    restored = client.post(f"/versions/{name}/restore", follow_redirects=True)

    assert "The version has been put back." in restored.text
    assert client.get("/browse?shelf=1").text == before
    # The moved layout was saved first, so restoring can itself be undone.
    assert "Saved versions (2)" in restored.text and "before restoring" in restored.text


def test_the_layout_can_be_saved_under_a_name(client):
    client.post("/layout/move", json={"shelves": {"1": [3, 2, 1]}})

    client.post("/versions/save", data={"label": "After the Move!"})

    page = client.get("/versions/").text
    assert "after the move" in page and "already saved" in page


def test_a_version_naming_a_removed_shelf_leaves_those_albums_out(client):
    client.post("/layout/move", json={"shelves": {"1": [1, 2], "3": [3]}})
    client.post("/versions/save", data={"label": "three"})
    client.post("/layout/move", json={"shelves": {"1": [1, 2, 3], "3": []}})
    client.post("/storage/shelves/3/delete")
    page = client.get("/versions/").text
    name = next(part.split("/restore")[0] for part in page.split("/versions/")[1:] if "--three" in part)

    restored = client.post(f"/versions/{name}/restore", follow_redirects=True)

    assert "1 album of that version no longer exists or lost its shelf" in restored.text
    assert "Moanin" in client.get("/unplaced").text


def test_clusters_can_be_reordered_renamed_and_merged(client):
    page = client.get("/clusters/").text
    assert page.index(">Jazz<") < page.index(">Rock<")

    client.post("/clusters/2/move", data={"direction": "up"})
    page = client.get("/clusters/").text
    assert page.index(">Rock<") < page.index(">Jazz<")
    # The proposal follows the new order: Rock now comes first on the shelves.
    client.post("/proposal/generate")
    assert "Fun House" in client.get("/browse?layout=proposal&shelf=1").text

    client.post("/clusters/1", data={"name": "Jazz: Cool"})
    assert "Jazz: Cool" in client.get("/clusters/").text
    assert client.post("/clusters/1", data={"name": " "}).status_code == 400

    assert "Tick at least two" in client.post("/clusters/merge", data={"cluster": "1"},
                                              follow_redirects=True).text
    client.post("/clusters/merge", data={"cluster": ["1", "2"], "name": "Everything"})

    page = client.get("/clusters/").text
    assert "Everything" in page and "Rock" not in page
    assert "Only the artists in the cluster “Everything”" in client.get("/artists/?cluster=1").text
    assert "The Stooges" in client.get("/artists/?cluster=1").text


def test_a_style_can_be_pointed_at_another_cluster_and_an_empty_cluster_removed(client):
    from sleeve_shelf.domain import Style
    from sleeve_shelf.persistence import JsonStore

    store = JsonStore(client.application.config["DATA_DIR"])
    store.save(Style, [Style(1, "Cool Jazz", 2)])
    assert "Cool Jazz" in client.get("/clusters/2").text

    client.post("/clusters/styles/1", data={"cluster_id": "1", "next": "/clusters/2"})

    assert store.load(Style) == [Style(1, "Cool Jazz", 1)]
    refused = client.post("/clusters/1/delete", follow_redirects=True)
    assert "Only a cluster without artists" in refused.text
    client.post("/artists/3", data={"start_year": "1967", "cluster_id": "1", "new_cluster": ""})
    client.post("/clusters/2/delete")
    assert ">Rock<" not in client.get("/clusters/").text


def test_dashboard_sums_up_and_lists_what_is_waiting(client):
    _add_new_artist(client)

    page = client.get("/dashboard/").text

    assert "albums in the layout" in page
    assert "1 artist without a confirmed cluster or a start year" in page
    assert "1 box set or bundle with a rough width" in page
    assert "1 LP without a place" in page
    assert "The current layout is saved." in page
    assert "no longer in your Discogs collection" not in page

    store = JsonStore(client.application.config["DATA_DIR"])
    albums = store.load(Album)
    albums[0].left_discogs = True
    store.save(Album, albums)
    assert "1 album no longer in your Discogs collection" in client.get("/dashboard/").text
    assert client.get("/").headers["Location"] == "/dashboard/"


def test_a_box_set_gets_its_measured_width(client):
    page = client.get("/albums/widths").text
    assert "To measure (1)" in page and "Box" in page and "Estimate: 3.0 cm" in page
    assert "/albums/widths" in client.get("/dashboard/").text

    bad = client.post("/albums/5/width", data={"width_cm": "thick"}, follow_redirects=True)
    assert "above zero" in bad.text

    client.post("/albums/5/width", data={"width_cm": "1,4"})

    page = client.get("/albums/widths").text
    assert "To measure (0)" in page and "Measured (1)" in page and 'value="1.4"' in page
    assert "rough width" not in client.get("/dashboard/").text
    # At 1.4 cm the box set fits on a 1.5 cm shelf, where 3 cm fitted nowhere.
    client.post("/proposal/generate")
    assert "Do not fit (0)" in client.get("/proposal/").text
    # The measured width survives a change of the width settings.
    client.post("/settings/", data={"base_width_cm": "0.5", "surcharge_180_gram_cm": "0.15",
                                    "surcharge_gatefold_cm": "0.2"})
    assert 'value="1.4"' in client.get("/albums/widths").text

    client.post("/albums/5/width", data={"width_cm": ""})
    assert "To measure (1)" in client.get("/albums/widths").text


def test_layout_has_a_tab_per_room_once_there_is_more_than_one(client):
    assert 'class="ss-tabs' not in client.get("/layout/").text

    client.post("/storage/cabinets/1", data={"name": "Kast", "location": "Woonkamer"})
    client.post("/storage/cabinets/new", data={"name": "Extern", "location": "Zolder"})
    client.post("/storage/cabinets/2/shelves/new", data={"name": "x", "width_cm": "5", "type": "", "layer": ""})

    first = client.get("/layout/").text
    assert 'class="ss-tabs' in first and "Woonkamer" in first and "Zolder" in first
    assert 'data-shelf="1"' in first and 'data-shelf="4"' not in first

    attic = client.get("/layout/?room=Zolder").text
    assert 'data-shelf="4"' in attic and 'data-shelf="1"' not in attic
    # The tray of unplaced albums is there in every room.
    assert 'data-list="0"' in attic
    # An unknown room falls back to the first.
    assert 'data-shelf="1"' in client.get("/layout/?room=Kelder").text
