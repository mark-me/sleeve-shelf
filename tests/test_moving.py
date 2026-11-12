"""Tests for the Move screen: what moves, where it goes, and what is shown before it does."""

import pytest

from sleeve_shelf.web.app import create_app
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
from sleeve_shelf.shelving.moving import OFF_SHELF, How, Kind, carry_out, find, plan, selection
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.shelving.placing import ShelvesChanged
from sleeve_shelf.library.versions import list_versions

CONSTANTS = Settings().width_constants


def _collection(tmp_path, last_shelf_cm=1.5):
    """Jazz (Chet Baker, a family, and Miles Davis) scattered over two cabinets and a
    showcase; Rock (Tindersticks) in the first cabinet. Every album is 0.5 cm, so a shelf of
    2 cm holds four.
    """
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

    assert 'href="/move/?kind=album&amp;id=11"' in client.get("/albums/11?tab=manage").text
    assert 'href="/move/?kind=artist&amp;id=2"' in client.get("/artists/2?tab=manage").text
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


# Moving in the proposal


def test_a_move_in_the_proposal_changes_only_the_proposal(tmp_path):
    from sleeve_shelf.domain import ProposedPlacement
    from sleeve_shelf.shelving.proposal import generate_proposal

    store = _collection(tmp_path)
    generate_proposal(store, CONSTANTS, 0)
    shelves_before = _shelves(store)
    jazz = selection(store, Kind.CLUSTER, 1, ProposedPlacement)

    planned = plan(store, jazz, How.END, 3, CONSTANTS, layout=ProposedPlacement)
    carry_out(store, planned, ProposedPlacement)

    assert _shelves(store) == shelves_before
    proposed = {p.album_id: p.shelf_id for p in store.load(ProposedPlacement)}
    assert all(proposed[album] == 3 for album in jazz.album_ids)
    assert all(isinstance(p, ProposedPlacement) for p in planned.placements)
    assert list_versions(store) == []


def test_the_move_screen_switches_between_the_shelves_and_the_proposal(tmp_path):
    from sleeve_shelf.domain import ProposedPlacement
    from sleeve_shelf.shelving.proposal import generate_proposal

    store = _collection(tmp_path)
    client = create_app(tmp_path).test_client()
    assert "The proposal" not in client.get("/move/").text
    generate_proposal(store, CONSTANTS, 0)
    shelves_before = _shelves(store)

    page = client.get("/move/?layout=proposal&kind=cluster&id=1").text
    assert "This changes only the proposal" in page and 'href="/clusters/"' in page
    assert 'name="layout" value="proposal"' in page and "layout=proposal" in page
    answer = client.post("/move/", data={"layout": "proposal", "kind": "cluster", "id": "1", "how": "end", "shelf": "3"})
    assert "layout=proposal" in answer.headers["Location"]
    assert "Only the proposal changed" in client.get(answer.headers["Location"]).text
    assert _shelves(store) == shelves_before
    proposed = {p.album_id: p.shelf_id for p in store.load(ProposedPlacement)}
    assert proposed[21] == 3
    # The proposal's second step leads here.
    assert "/move/?layout=proposal" in client.get("/proposal/").text


# Larger with one tap


def test_what_is_chosen_can_be_made_larger_up_to_its_cluster(tmp_path):
    from sleeve_shelf.shelving.moving import wider

    store = _collection(tmp_path)

    album = selection(store, Kind.ALBUM, 11)
    assert [(s.kind, s.id) for s in wider(store, album)] == [(Kind.ARTIST, 1), (Kind.FAMILY, 1), (Kind.CLUSTER, 1)]
    # Miles Davis is in no family: the artist goes straight to its cluster.
    assert [(s.kind, s.id) for s in wider(store, selection(store, Kind.ARTIST, 2))] == [(Kind.CLUSTER, 1)]
    assert [(s.kind, s.id) for s in wider(store, selection(store, Kind.FAMILY, 1))] == [(Kind.CLUSTER, 1)]
    assert wider(store, selection(store, Kind.CLUSTER, 1)) == []
    # The cluster counts the albums that would move: the one in the showcase stays.
    assert wider(store, album)[-1].album_ids == (11, 22, 21)


def test_the_move_screen_offers_the_larger_choices_and_layout_leads_to_it(tmp_path):
    _collection(tmp_path)
    client = create_app(tmp_path).test_client()

    page = client.get("/move/?kind=album&id=11").text
    assert "Larger:" in page
    assert "kind=artist&amp;id=1" in page and "kind=family&amp;id=1" in page and "kind=cluster&amp;id=1" in page
    layout = client.get("/layout/").text
    assert 'id="send-more"' in layout and 'data-move-url="/move/"' in layout and 'data-artist="1"' in layout


# All cabinets at a glance


def test_every_shelf_shows_its_clusters_as_runs_to_one_scale(tmp_path):
    from sleeve_shelf.shelving.at_a_glance import at_a_glance

    store = _collection(tmp_path)
    glance = at_a_glance(store, CONSTANTS)

    assert [entry["cabinet"].name for entry in glance["cabinets"]] == ["Kast", "Koffer"]
    shelf_b = glance["cabinets"][0]["shelves"][1]
    # Shelf b: three Tindersticks albums, then Round Midnight of Jazz.
    assert [(run["cluster"], run["albums"]) for run in shelf_b["runs"]] == [("Rock", 3), ("Jazz", 1)]
    assert shelf_b["filled_cm"] == pytest.approx(4 * CONSTANTS.base_per_disc)
    assert [c["name"] for c in glance["clusters"]] == ["Jazz", "Rock"]
    assert glance["cabinets"][0]["widest_cm"] >= 2.0


def test_layout_shows_the_whole_and_gives_it_anew_after_a_move(tmp_path):
    _collection(tmp_path)
    client = create_app(tmp_path).test_client()

    page = client.get("/layout/").text
    assert "All cabinets at a glance" in page and 'data-glance-url="/layout/glance"' in page
    assert page.count('class="ss-glance-shelf') == 5
    fragment = client.get("/layout/glance").text
    assert "ss-glance-run" in fragment and "<html" not in fragment
    # Should the overview fail to come up to date after a move, the page says so; hidden until then.
    assert 'data-glance-stale role="status" hidden' in page and "could not be brought up to date" in page


def test_a_move_meant_for_a_proposal_that_is_gone_changes_nothing(tmp_path):
    from sleeve_shelf.shelving.proposal import discard_proposal, generate_proposal

    store = _collection(tmp_path)
    client = create_app(tmp_path).test_client()
    generate_proposal(store, CONSTANTS, 0)
    page = client.get("/move/?layout=proposal&kind=cluster&id=1").text
    assert 'name="layout" value="proposal"' in page
    discard_proposal(store)
    shelves_before = _shelves(store)

    answer = client.post("/move/", data={"layout": "proposal", "kind": "cluster", "id": "1", "how": "end", "shelf": "3"})

    assert answer.headers["Location"] == "/move/?gone=1"
    assert "nothing was moved" in client.get(answer.headers["Location"]).text
    assert _shelves(store) == shelves_before
    assert list_versions(store) == []
    # Layout's drags and its shelf list refuse likewise.
    dragged = client.post("/layout/move?layout=proposal", json={"shelves": {"3": [11, 21]}})
    sent = client.post("/layout/send?layout=proposal", json={"albums": [11], "shelf": 1})
    assert dragged.status_code == 409 and sent.status_code == 409
    assert _shelves(store) == shelves_before


def test_a_plan_for_a_proposal_discarded_meanwhile_does_not_bring_it_back(tmp_path):
    from sleeve_shelf.domain import ProposedPlacement
    from sleeve_shelf.shelving.placing import ProposalGone
    from sleeve_shelf.shelving.proposal import discard_proposal, generate_proposal

    store = _collection(tmp_path)
    generate_proposal(store, CONSTANTS, 0)
    jazz = selection(store, Kind.CLUSTER, 1, ProposedPlacement)
    planned = plan(store, jazz, How.END, 3, CONSTANTS, layout=ProposedPlacement)
    # Another request discards the proposal between working the plan out and saving it.
    discard_proposal(store)

    with pytest.raises(ProposalGone):
        carry_out(store, planned, ProposedPlacement)
    assert not store.exists(ProposedPlacement)


def test_discarding_waits_while_the_proposal_is_being_changed(tmp_path):
    import threading

    from sleeve_shelf.domain import ProposedPlacement
    from sleeve_shelf.shelving.placing import proposal_edit
    from sleeve_shelf.shelving.proposal import discard_proposal, generate_proposal

    store = _collection(tmp_path)
    generate_proposal(store, CONSTANTS, 0)
    holding, release = threading.Event(), threading.Event()

    def change():
        with proposal_edit(store):
            holding.set()
            release.wait(5)

    changing = threading.Thread(target=change)
    changing.start()
    holding.wait(5)
    discarding = threading.Thread(target=discard_proposal, args=(store,))
    discarding.start()
    discarding.join(0.3)
    # While the change holds the proposal, discarding waits.
    assert discarding.is_alive() and store.exists(ProposedPlacement)
    release.set()
    changing.join(5)
    discarding.join(5)
    assert not store.exists(ProposedPlacement)


def test_two_clusters_of_one_name_stay_two_at_a_glance(tmp_path):
    from sleeve_shelf.library.clusters import rename_cluster
    from sleeve_shelf.shelving.at_a_glance import at_a_glance

    store = _collection(tmp_path)
    # Renamed to the name of the other: nothing stops that.
    rename_cluster(store, 2, "Jazz")

    shelf_b = at_a_glance(store, CONSTANTS)["cabinets"][0]["shelves"][1]

    assert [(run["cluster"], run["cluster_id"]) for run in shelf_b["runs"]] == [("Jazz", 2), ("Jazz", 1)]
    assert shelf_b["runs"][0]["index"] != shelf_b["runs"][1]["index"]
    fragment = create_app(tmp_path).test_client().get("/layout/glance").text
    assert 'data-cluster="1" data-cluster-name="Jazz"' in fragment and 'data-cluster="2" data-cluster-name="Jazz"' in fragment


def test_an_artist_without_a_confirmed_cluster_shows_the_cluster_it_is_sorted_in(tmp_path):
    from sleeve_shelf.domain import ArtistClusterAssignment, Style
    from sleeve_shelf.shelving.at_a_glance import at_a_glance

    store = _collection(tmp_path)
    # Nobody Knows has no cluster of its own; its album's style points to Rock.
    store.save(Style, [Style(1, "Indie Rock", 2)])
    albums = store.load(Album)
    next(a for a in albums if a.id == 41).style_ids = [1]
    store.save(Album, albums)
    assert all(a.artist_id != 4 for a in store.load(ArtistClusterAssignment))

    shelf_d = at_a_glance(store, CONSTANTS)["cabinets"][1]["shelves"][0]

    assert [(run["cluster"], run["cluster_id"]) for run in shelf_d["runs"]] == [("Jazz", 1), ("Rock", 2)]


def test_moving_an_album_the_proposal_has_no_place_for_says_it_adds_it(tmp_path):
    from sleeve_shelf.domain import ProposedPlacement
    from sleeve_shelf.shelving.moving import stands_nowhere
    from sleeve_shelf.shelving.proposal import generate_proposal

    store = _collection(tmp_path)
    generate_proposal(store, CONSTANTS, 0)
    # The proposal leaves one album out: as though it had no room for it.
    proposed = [p for p in store.load(ProposedPlacement) if p.album_id != 22]
    store.save(ProposedPlacement, proposed)
    client = create_app(tmp_path).test_client()

    assert stands_nowhere(store, selection(store, Kind.ALBUM, 22), ProposedPlacement)
    assert not stands_nowhere(store, selection(store, Kind.ALBUM, 22))
    assert not stands_nowhere(store, selection(store, Kind.ARTIST, 2), ProposedPlacement)
    page = client.get("/move/?layout=proposal&kind=album&id=22").text
    assert "no place in the proposal: it did not fit" in page
    assert "no place in the proposal" not in client.get("/move/?layout=proposal&kind=album&id=21").text
    # Moving it there adds it, and only to the proposal.
    client.post("/move/", data={"layout": "proposal", "kind": "album", "id": "22", "how": "end", "shelf": "3"})
    assert any(p.album_id == 22 and p.shelf_id == 3 for p in store.load(ProposedPlacement))


def test_changes_saved_together_are_all_undone_when_one_fails(tmp_path):
    from sleeve_shelf.domain import ArtistClusterAssignment, ProposedPlacement

    store = _collection(tmp_path)
    placements = (tmp_path / "placement_current.json").read_bytes()

    with pytest.raises(RuntimeError):
        with store.together(Placement, ArtistClusterAssignment, ProposedPlacement):
            store.save(Placement, [])
            store.save(ProposedPlacement, [Placement(11, 1, 0)])
            raise RuntimeError("the disk is full")

    assert (tmp_path / "placement_current.json").read_bytes() == placements
    # A file that was not there before is gone again.
    assert not store.exists(ProposedPlacement)


def test_a_move_in_the_proposal_and_its_cluster_stand_or_fall_together(tmp_path, monkeypatch):
    from sleeve_shelf.domain import ProposedPlacement
    from sleeve_shelf.shelving import moving
    from sleeve_shelf.shelving.proposal import generate_proposal

    store = _collection(tmp_path)
    generate_proposal(store, CONSTANTS, 0)
    proposal = (tmp_path / "placement_proposal.json").read_bytes()
    assignments = (tmp_path / "cluster_assignments.json").read_bytes()
    planned = plan(store, selection(store, Kind.ALBUM, 41, ProposedPlacement), How.END, 3, CONSTANTS, layout=ProposedPlacement)

    def failing(*args):
        raise OSError("could not write")

    monkeypatch.setattr(moving, "set_cluster", failing)
    with pytest.raises(OSError):
        carry_out(store, planned, ProposedPlacement, (4, 2))

    assert (tmp_path / "placement_proposal.json").read_bytes() == proposal
    assert (tmp_path / "cluster_assignments.json").read_bytes() == assignments
