"""Tests for the Move screen: what moves, where it goes, and what is shown before it does."""

import pytest

from sleeve_shelf import create_app
from sleeve_shelf.config import Settings
from sleeve_shelf.domain import (
    Album,
    AliasGroup,
    Artist,
    ArtistClusterAssignment,
    Cabinet,
    Cluster,
    Placement,
    Shelf,
    ShelfType,
)
from sleeve_shelf.moving import OFF_SHELF, How, Kind, carry_out, find, plan, selection
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.placing import ShelvesChanged
from sleeve_shelf.versions import list_versions

CONSTANTS = Settings().width_constants


def _collection(tmp_path, last_shelf_cm=1.5):
    """Jazz (Chet Baker, a family, and Miles Davis) scattered over two cabinets and a
    showcase; Rock (Tindersticks) in the first cabinet. Every album is 0.5 cm, so a shelf of
    2 cm holds four."""
    store = JsonStore(tmp_path)
    store.save(Cluster, [Cluster(1, "Jazz", 0), Cluster(2, "Rock", 1)])
    store.save(AliasGroup, [AliasGroup(1, "Chet Baker")])
    store.save(
        Artist,
        [Artist(1, "Chet Baker", alias_group_id=1, start_year=1952), Artist(2, "Miles Davis", start_year=1955),
         Artist(3, "Tindersticks", start_year=1993), Artist(4, "Nobody Knows")],
    )
    store.save(
        ArtistClusterAssignment,
        [ArtistClusterAssignment(1, 1, True), ArtistClusterAssignment(2, 1, True),
         ArtistClusterAssignment(3, 2, True)],
    )
    store.save(
        Album,
        [Album(11, 1, "Chet", original_release_year=1954), Album(12, 1, "Chet Again", original_release_year=1956),
         Album(21, 2, "Kind of Blue", original_release_year=1959), Album(22, 2, "Round Midnight", original_release_year=1957),
         Album(41, 4, "Unknown", original_release_year=1970)]
        + [Album(i, 3, f"Tindersticks {i}", original_release_year=1960 + i) for i in range(31, 37)],
    )
    store.save(Cabinet, [Cabinet(1, "Kast", position=0), Cabinet(2, "Koffer", position=1)])
    store.save(
        Shelf,
        [Shelf(1, 1, "a", width_cm=2.0, position=0), Shelf(2, 1, "b", width_cm=2.0, position=1),
         Shelf(3, 1, "c", width_cm=last_shelf_cm, position=2), Shelf(4, 2, "d", width_cm=2.0, position=0),
         Shelf(5, 2, "e", width_cm=2.0, type=ShelfType.TOP_LOADER, position=1, is_showcase=True)],
    )
    store.save(
        Placement,
        [Placement(31, 1, 0), Placement(32, 1, 1), Placement(33, 1, 2),
         Placement(34, 2, 0), Placement(35, 2, 1), Placement(36, 2, 2), Placement(22, 2, 3),
         Placement(11, 3, 0), Placement(21, 4, 0), Placement(41, 4, 1), Placement(12, 5, 0)],
    )
    return store


def _shelves(store):
    shelves: dict[int, list[int]] = {}
    for p in sorted(store.load(Placement), key=lambda p: (p.shelf_id, p.position)):
        shelves.setdefault(p.shelf_id, []).append(p.album_id)
    return shelves


def test_what_moves_is_what_stands_on_a_sorted_shelf_in_sorting_order(tmp_path):
    store = _collection(tmp_path)

    # Chet Baker, then Miles Davis by year; Chet's album in the showcase stays there.
    assert selection(store, Kind.CLUSTER, 1).album_ids == (11, 22, 21)
    assert selection(store, Kind.FAMILY, 1).album_ids == (11,)
    assert selection(store, Kind.ARTIST, 2).album_ids == (22, 21)
    # One album moves whatever it stands on.
    assert selection(store, Kind.ALBUM, 12).album_ids == (12,)
    assert selection(store, Kind.ARTIST, 99) is None
    assert [(kind, name, albums) for kind, _, name, albums in find(store, "chet")] == [
        (Kind.FAMILY, "Chet Baker", 1), (Kind.ARTIST, "Chet Baker", 1),
        (Kind.ALBUM, "Chet Baker — Chet", 1), (Kind.ALBUM, "Chet Baker — Chet Again", 1),
    ]


def test_at_the_front_it_runs_on_and_what_stood_there_moves_up(tmp_path):
    store = _collection(tmp_path)
    before = _shelves(store)

    planned = plan(store, selection(store, Kind.CLUSTER, 1), How.FRONT, 2, CONSTANTS)

    # Nothing has changed yet: the plan only says what would.
    assert _shelves(store) == before
    assert [(c.name, c.before, c.after) for c in planned.changes] == [
        ("Kast › b", 4, 4), ("Kast › c", 1, 2), ("Koffer › d", 2, 1),
    ]
    carry_out(store, planned)
    assert _shelves(store) == {1: [31, 32, 33], 2: [11, 22, 21, 34], 3: [35, 36], 4: [41], 5: [12]}
    assert len(list_versions(store)) == 1


def test_what_no_longer_fits_stays_at_the_end_of_the_cabinet_and_is_marked(tmp_path):
    store = _collection(tmp_path, last_shelf_cm=0.5)

    planned = plan(store, selection(store, Kind.CLUSTER, 1), How.FRONT, 2, CONSTANTS)

    last = next(c for c in planned.changes if c.name == "Kast › c")
    assert (last.after, last.over) == (2, True)
    # At the front of a showcase it is simply put in front: nothing runs on.
    planned = plan(store, selection(store, Kind.ARTIST, 2), How.FRONT, 5, CONSTANTS)
    carry_out(store, planned)
    assert _shelves(store)[5] == [22, 21, 12]


def test_at_the_end_of_a_shelf_or_off_the_shelves(tmp_path):
    store = _collection(tmp_path)

    carry_out(store, plan(store, selection(store, Kind.ARTIST, 2), How.END, 1, CONSTANTS))
    assert _shelves(store)[1] == [31, 32, 33, 22, 21]

    carry_out(store, plan(store, selection(store, Kind.ALBUM, 22), How.END, OFF_SHELF, CONSTANTS))
    assert 22 not in {p.album_id for p in store.load(Placement)}
    with pytest.raises(ShelvesChanged):
        plan(store, selection(store, Kind.ALBUM, 21), How.END, 99, CONSTANTS)


def test_where_it_belongs_is_next_to_what_it_goes_with_as_the_shelves_stand(tmp_path):
    store = _collection(tmp_path)
    # Miles Davis' early album was put away at the end of the other cabinet.
    carry_out(store, plan(store, selection(store, Kind.ALBUM, 22), How.END, 4, CONSTANTS))

    planned = plan(store, selection(store, Kind.ALBUM, 22), How.BELONGS, None, CONSTANTS)
    carry_out(store, planned)
    # Back next to Miles Davis' other album, before it by year.
    assert _shelves(store)[4] == [22, 21, 41]

    # An artist without a cluster has no place it belongs to: it stays where it is.
    planned = plan(store, selection(store, Kind.ALBUM, 41), How.BELONGS, None, CONSTANTS)
    assert planned.without_spot == (41,) and planned.changes == ()


def test_the_move_screen_finds_shows_and_moves(tmp_path):
    _collection(tmp_path)
    client = create_app(tmp_path).test_client()

    found = client.get("/move/?q=miles").text
    assert 'href="/move/?kind=artist&amp;id=2"' in found
    chosen = client.get("/move/?kind=artist&id=2").text
    assert "Miles Davis" in chosen and "2 albums on a shelf" in chosen and "What changes" not in chosen

    preview = client.get("/move/?kind=artist&id=2&how=end&shelf=1").text
    assert "2 albums move; these shelves change:" in preview and "Kast › a" in preview
    assert _shelves(JsonStore(tmp_path))[1] == [31, 32, 33]

    moved = client.post("/move/", data={"kind": "artist", "id": "2", "how": "end", "shelf": "1"})
    assert moved.headers["Location"] == "/move/?kind=artist&id=2&done=2&cabinet=1"
    assert "2 albums moved." in client.get(moved.headers["Location"]).text
    assert _shelves(JsonStore(tmp_path))[1] == [31, 32, 33, 22, 21]

    assert client.get("/move/?kind=artist&id=99").status_code == 404
    assert client.post("/move/", data={"kind": "artist", "id": "2", "how": "end"}).status_code == 400
    assert client.post("/move/", data={"kind": "artist", "id": "2", "how": "end", "shelf": "99"}).status_code == 400


def test_the_pages_of_an_album_artist_family_and_cluster_lead_to_the_move_screen(tmp_path):
    _collection(tmp_path)
    client = create_app(tmp_path).test_client()

    assert 'href="/move/?kind=album&amp;id=11"' in client.get("/albums/11").text
    assert 'href="/move/?kind=artist&amp;id=2"' in client.get("/artists/2").text
    assert 'href="/move/?kind=family&amp;id=1"' in client.get("/families/").text
    assert 'href="/move/?kind=cluster&amp;id=1"' in client.get("/clusters/1").text


def test_a_shelf_holds_at_least_what_stands_on_it_now_whatever_its_estimate_says(tmp_path):
    store = _collection(tmp_path)
    # Shelf b's width from the workbook is an estimate that came out too narrow: its four
    # albums take 2 cm.
    store.save(Shelf, [s if s.id != 2 else Shelf(2, 1, "b", width_cm=1.0, position=1) for s in store.load(Shelf)])

    carry_out(store, plan(store, selection(store, Kind.ALBUM, 21), How.FRONT, 2, CONSTANTS))

    # Kind of Blue goes in front; one album moves on to shelf c, not three.
    assert _shelves(store)[2] == [21, 34, 35, 36]
    assert _shelves(store)[3] == [22, 11]
