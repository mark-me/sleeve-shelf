"""Tests for moving albums by hand, rearranging shelves, and the location rules."""

import pytest

from sleeve_shelf.config import Settings
from sleeve_shelf.domain import (
    Album,
    AliasGroup,
    Artist,
    ArtistClusterAssignment,
    Cabinet,
    Cluster,
    LocationRule,
    LocationRuleTarget,
    Placement,
    PlacementSource,
    ProposedPlacement,
    Shelf,
    ShelfType,
)
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.placing import (
    ShelvesChanged,
    move_albums,
    place_cluster,
    place_family,
    rearrange_shelves,
    remove_rule,
    set_rule,
)
from sleeve_shelf.versions import list_versions


@pytest.fixture
def store(tmp_path):
    store = JsonStore(tmp_path)
    store.save(Artist, [Artist(1, "Tindersticks")])
    store.save(Album, [Album(i, 1, f"Album {i}") for i in range(1, 6)])
    store.save(Cabinet, [Cabinet(1, "Kast")])
    store.save(Shelf, [Shelf(1, 1, "a"), Shelf(2, 1, "b")])
    store.save(Placement, [Placement(1, 1, 0), Placement(2, 1, 1), Placement(3, 2, 0)])
    return store


def _shelves(store, entity=Placement):
    """Per shelf, its albums in order."""
    shelves: dict[int, list[int]] = {}
    for p in sorted(store.load(entity), key=lambda p: (p.shelf_id, p.position)):
        shelves.setdefault(p.shelf_id, []).append(p.album_id)
    return shelves


def test_albums_go_to_the_end_of_a_shelf_and_a_version_is_kept_first(store):
    touched = move_albums(store, [4, 1], 2)

    assert _shelves(store) == {1: [2], 2: [3, 4, 1]}
    assert touched == {1, 2}
    assert all(p.source == PlacementSource.MANUAL for p in store.load(Placement) if p.album_id in (1, 4))
    assert len(list_versions(store)) == 1


def test_albums_taken_off_their_shelf_stand_nowhere(store):
    assert move_albums(store, [3], None) == {2}
    assert _shelves(store) == {1: [1, 2]}


def test_moving_unknown_albums_or_shelves_changes_nothing(store):
    for album_ids, shelf_id in (([9], 1), ([1], 9), ([1, 1], 2)):
        with pytest.raises(ShelvesChanged):
            move_albums(store, album_ids, shelf_id)
    assert _shelves(store) == {1: [1, 2], 2: [3]}
    assert list_versions(store) == []


def test_a_drag_gives_the_shelves_new_contents(store):
    rearrange_shelves(store, {1: [2, 3], 2: [1]}, off_shelf=[])
    assert _shelves(store) == {1: [2, 3], 2: [1]}

    # The tray takes an album off its shelf.
    rearrange_shelves(store, {2: []}, off_shelf=[1])
    assert _shelves(store) == {1: [2, 3]}


def test_nothing_drops_off_a_shelf_without_being_named(store):
    # Album 2 stood on shelf 1 and is named nowhere: the shelves have changed since.
    with pytest.raises(ShelvesChanged):
        rearrange_shelves(store, {1: [1]})
    for contents in ({1: [1, 2, 9]}, {9: [1, 2]}, {1: [1, 2], 2: [2, 3]}):
        with pytest.raises(ShelvesChanged):
            rearrange_shelves(store, contents)
    assert _shelves(store) == {1: [1, 2], 2: [3]}


def test_the_proposal_is_changed_without_touching_the_shelves_or_keeping_a_version(store):
    store.save(ProposedPlacement, [ProposedPlacement(1, 1, 0), ProposedPlacement(2, 2, 0)])

    move_albums(store, [1], 2, ProposedPlacement)
    rearrange_shelves(store, {2: [1, 2]}, entity=ProposedPlacement)

    assert _shelves(store, ProposedPlacement) == {2: [1, 2]}
    assert _shelves(store) == {1: [1, 2], 2: [3]}
    assert list_versions(store) == []


def test_a_target_has_one_rule_and_a_new_one_replaces_it(store):
    first = set_rule(store, LocationRuleTarget.ARTIST, 1, 1, "by the door")
    set_rule(store, LocationRuleTarget.ALBUM, 2, 1)
    second = set_rule(store, LocationRuleTarget.ARTIST, 1, 2)

    rules = {(r.target_type, r.target_id): r for r in store.load(LocationRule)}
    assert len(rules) == 2 and rules[(LocationRuleTarget.ARTIST, 1)].cabinet_id == 2
    # A replaced rule's id is not handed out again.
    assert second.id != first.id

    remove_rule(store, second.id)
    assert [r.target_type for r in store.load(LocationRule)] == [LocationRuleTarget.ALBUM]


def _two_clusters(tmp_path, last_shelf_cm=1.5):
    """Jazz scattered over two cabinets and a showcase, Rock in the first cabinet. Every
    album is 0.5 cm, so a shelf of 2 cm holds four."""
    store = JsonStore(tmp_path)
    store.save(Cluster, [Cluster(1, "Jazz", 0), Cluster(2, "Rock", 1)])
    store.save(
        Artist,
        [Artist(1, "Chet Baker", start_year=1952), Artist(2, "Miles Davis", start_year=1955),
         Artist(3, "Tindersticks", start_year=1993)],
    )
    store.save(
        ArtistClusterAssignment,
        [ArtistClusterAssignment(1, 1, True), ArtistClusterAssignment(2, 1, True),
         ArtistClusterAssignment(3, 2, True)],
    )
    store.save(
        Album,
        [Album(11, 1, "Chet", original_release_year=1954), Album(12, 1, "Chet Again", original_release_year=1956),
         Album(21, 2, "Kind of Blue", original_release_year=1959), Album(22, 2, "Round Midnight", original_release_year=1957)]
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
         Placement(11, 3, 0), Placement(21, 4, 0), Placement(12, 5, 0)],
    )
    return store


def test_a_cluster_stands_together_from_a_shelf_on_and_what_stood_there_moves_up(tmp_path):
    store = _two_clusters(tmp_path)

    result = place_cluster(store, 1, 2, Settings().width_constants)

    # In sorting order (Chet Baker, then Miles Davis by year) from the start of shelf b;
    # Rock moves up behind it onto c. Shelf a and the other cabinet keep theirs, the
    # showcase its sample.
    assert _shelves(store) == {1: [31, 32, 33], 2: [11, 22, 21, 34], 3: [35, 36], 5: [12]}
    assert (result.moved, result.shelf_ids, result.over_cm) == (3, (2, 3), 0.0)
    assert len(list_versions(store)) == 1


def test_what_no_longer_fits_stays_at_the_end_of_the_cabinet_and_is_reported(tmp_path):
    store = _two_clusters(tmp_path, last_shelf_cm=0.5)

    result = place_cluster(store, 1, 2, Settings().width_constants)

    assert _shelves(store)[3] == [35, 36]
    assert result.over_cm == pytest.approx(0.5)
    # A showcase is no shelf to start on.
    with pytest.raises(ShelvesChanged):
        place_cluster(store, 1, 5, Settings().width_constants)


def test_the_cluster_page_moves_the_cluster_and_says_where_it_went(tmp_path):
    from sleeve_shelf import create_app

    _two_clusters(tmp_path, last_shelf_cm=0.5)
    client = create_app(tmp_path).test_client()

    page = client.get("/clusters/1").text
    assert "3 albums of this cluster that stand on a shelf (1.5 cm)" in page
    # The showcase is no shelf to start on.
    assert '<option value="2">Kast › b</option>' in page and "Koffer › e" not in page

    moved = client.post("/clusters/1/place", data={"shelf_id": "2"})
    assert moved.headers["Location"].startswith("/clusters/1?placed=3&shelf=2&over=0.5")
    page = client.get(moved.headers["Location"]).text
    assert "3 albums of this cluster now stand from Kast › b on." in page
    assert "holds 0.5 cm more than its width" in page and 'href="/layout/go?to=1"' in page
    assert client.post("/clusters/1/place", data={"shelf_id": "5"}).status_code == 400


def test_a_family_moves_together_too_and_its_page_says_where_it_went(tmp_path):
    from sleeve_shelf import create_app

    store = _two_clusters(tmp_path)
    store.save(AliasGroup, [AliasGroup(1, "Chet Baker")])
    store.save(
        Artist,
        [Artist(1, "Chet Baker", alias_group_id=1, start_year=1952),
         Artist(2, "Miles Davis", start_year=1955), Artist(3, "Tindersticks", start_year=1993)],
    )

    result = place_family(store, 1, 1, Settings().width_constants)

    # Chet Baker's album from shelf c to the start of shelf a; the rest moves up. His album
    # in the showcase stays there.
    assert _shelves(store) == {1: [11, 31, 32, 33], 2: [34, 35, 36, 22], 4: [21], 5: [12]}
    assert result.moved == 1

    client = create_app(tmp_path).test_client()
    page = client.get("/families/").text
    assert "The 1 album of this family that stands on a shelf (0.5 cm)" in page
    moved = client.post("/families/1/place", data={"shelf_id": "2"})
    assert moved.headers["Location"].startswith("/families/?family=1&placed=1&shelf=2")
    assert "1 album of this family now stands from Kast › b on." in client.get(moved.headers["Location"]).text
    assert client.post("/families/9/place", data={"shelf_id": "2"}).status_code == 404
