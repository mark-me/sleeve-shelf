"""Tests for choosing a spot for an album that stands nowhere yet.

The other clusters its styles point to, and right before or after an album one chooses.
"""

import pytest

from sleeve_shelf.access import set_password
from sleeve_shelf.config import Settings
from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    Cabinet,
    Cluster,
    Placement,
    Shelf,
    Style,
)
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.shelving.moving import How, Kind, carry_out, cluster_offer, plan, selection
from sleeve_shelf.shelving.placing import ShelvesChanged
from sleeve_shelf.shelving.spots import other_spots, place_in_cluster, suggested_spots
from sleeve_shelf.sorting.order import clusters_by_styles
from sleeve_shelf.web.app import create_app

CONSTANTS = Settings().width_constants


def _collection(tmp_path):
    """Jazz (Miles Davis), Rock (Cream) and Blues (Muddy Waters), a shelf each; the Jimi Hendrix
    Experience has no cluster of its own, and its two albums stand nowhere. Their styles point to
    Blues twice and to Rock once.
    """
    store = JsonStore(tmp_path)
    store.save(Cluster, [Cluster(1, "Jazz", 0), Cluster(2, "Rock", 1), Cluster(3, "Blues", 2)])
    store.save(Style, [Style(1, "Hard Bop", 1), Style(2, "Blues Rock", 3), Style(3, "Psychedelic Rock", 2)])
    store.save(
        Artist,
        [Artist(1, "Miles Davis", start_year=1955), Artist(2, "Cream", start_year=1966),
         Artist(3, "Muddy Waters", start_year=1950), Artist(4, "The Jimi Hendrix Experience", start_year=1967)],
    )
    store.save(
        ArtistClusterAssignment,
        [ArtistClusterAssignment(1, 1, True), ArtistClusterAssignment(2, 2, True), ArtistClusterAssignment(3, 3, True)],
    )
    store.save(
        Album,
        [Album(11, 1, "Kind of Blue", original_release_year=1959, style_ids=[1]),
         Album(21, 2, "Fresh Cream", original_release_year=1966, style_ids=[3]),
         Album(22, 2, "Disraeli Gears", original_release_year=1967, style_ids=[3]),
         Album(31, 3, "Folk Singer", original_release_year=1964, style_ids=[2]),
         Album(41, 4, "Axis: Bold As Love", original_release_year=1967, style_ids=[2, 3]),
         Album(42, 4, "Electric Ladyland", original_release_year=1968, style_ids=[2])],
    )
    store.save(Cabinet, [Cabinet(1, "Kast", position=0)])
    store.save(
        Shelf,
        [Shelf(1, 1, "a", width_cm=30.0, position=0), Shelf(2, 1, "b", width_cm=30.0, position=1),
         Shelf(3, 1, "c", width_cm=30.0, position=2)],
    )
    store.save(
        Placement,
        [Placement(11, 1, 0), Placement(21, 2, 0), Placement(22, 2, 1), Placement(31, 3, 0)],
    )
    return store


def _shelves(store):
    shelves: dict[int, list[int]] = {}
    for p in sorted(store.load(Placement), key=lambda p: (p.shelf_id, p.position)):
        shelves.setdefault(p.shelf_id, []).append(p.album_id)
    return shelves


def _confirmed(store, artist_id):
    return next((a.cluster_id for a in store.load(ArtistClusterAssignment) if a.artist_id == artist_id and a.confirmed), None)


@pytest.fixture
def store(tmp_path):
    return _collection(tmp_path)


@pytest.fixture
def client(store):
    return create_app(store.data_dir).test_client()


def test_the_clusters_the_styles_point_to_come_most_first():
    albums = [Album(1, 1, "a", original_release_year=1970, style_ids=[2, 3]), Album(2, 1, "b", style_ids=[2])]
    styles = {2: Style(2, "Blues Rock", 3), 3: Style(3, "Psychedelic Rock", 2)}

    assert clusters_by_styles(albums, styles) == [3, 2]
    assert clusters_by_styles([], styles) == []


def test_a_spot_says_its_cluster_is_only_proposed_and_another_cluster_is_offered(store):
    spot = suggested_spots(store, CONSTANTS)[41]
    assert (spot.shelf_id, spot.cluster_id, spot.cluster_proposed) == (3, 3, True)

    others = other_spots(store, 41, CONSTANTS)
    assert [(s.shelf_id, s.cluster_id) for s in others] == [(2, 2)]


def test_a_confirmed_cluster_offers_no_other_spots(store):
    store.save(ArtistClusterAssignment, [*store.load(ArtistClusterAssignment), ArtistClusterAssignment(4, 3, True)])

    assert suggested_spots(store, CONSTANTS)[41].cluster_proposed is False
    assert other_spots(store, 41, CONSTANTS) == []


def test_placing_in_another_cluster_puts_the_artist_there_when_asked(store):
    spot = place_in_cluster(store, 41, 2, CONSTANTS, confirm=True)

    assert spot.shelf_id == 2
    assert 41 in _shelves(store)[2]
    assert _confirmed(store, 4) == 2


def test_placing_in_another_cluster_can_leave_the_artist_without_one(store):
    place_in_cluster(store, 41, 2, CONSTANTS, confirm=False)

    assert 41 in _shelves(store)[2]
    assert _confirmed(store, 4) is None


def test_a_cluster_not_offered_places_nothing(store):
    before = _shelves(store)

    assert place_in_cluster(store, 41, 1, CONSTANTS, confirm=True) is None
    assert _shelves(store) == before
    assert _confirmed(store, 4) is None


def test_an_album_goes_right_before_or_after_the_album_chosen(store):
    axis = selection(store, Kind.ALBUM, 41)

    after = plan(store, axis, How.AFTER, None, CONSTANTS, next_to=21)
    assert (after.shelf_id, after.next_to) == (2, 21)
    carry_out(store, after)
    assert _shelves(store)[2] == [21, 41, 22]

    carry_out(store, plan(store, axis, How.BEFORE, None, CONSTANTS, next_to=21))
    assert _shelves(store)[2] == [41, 21, 22]


def test_next_to_an_album_on_no_shelf_or_to_itself_is_refused(store):
    axis = selection(store, Kind.ALBUM, 41)

    with pytest.raises(ShelvesChanged):
        plan(store, axis, How.AFTER, None, CONSTANTS, next_to=42)
    with pytest.raises(ShelvesChanged):
        plan(store, axis, How.BEFORE, None, CONSTANTS, next_to=41)


def test_the_cluster_of_the_album_next_to_is_offered_when_it_is_another(store):
    axis = selection(store, Kind.ALBUM, 41)

    assert cluster_offer(store, axis, 21) == {
        "artist_id": 4, "artist": "The Jimi Hendrix Experience", "cluster_id": 2, "cluster": "Rock",
    }
    # Blues is where the styles put it already.
    assert cluster_offer(store, axis, 31) is None
    store.save(ArtistClusterAssignment, [*store.load(ArtistClusterAssignment), ArtistClusterAssignment(4, 3, True)])
    assert cluster_offer(store, axis, 21) is None


def test_the_album_page_offers_the_other_cluster_and_somewhere_else(client):
    page = client.get("/albums/41?tab=manage").get_data(as_text=True)

    assert "is proposed from the styles" in page
    assert "Or in Rock" in page
    assert "Also put The Jimi Hendrix Experience in Rock" in page
    assert "/move/?kind=album&amp;id=41#next-to" in page


def test_putting_it_in_the_other_cluster_from_the_album_page(client, store):
    answer = client.post("/albums/41/place", data={"back": "album", "cluster": "2", "confirm_cluster": "1"})

    assert answer.status_code == 302
    assert 41 in _shelves(store)[2]
    assert _confirmed(store, 4) == 2


def test_the_list_of_albums_to_place_links_to_the_other_spots(client):
    page = client.get("/unplaced").get_data(as_text=True)

    assert "Other spots" in page
    assert "/albums/41?tab=manage#spot" in page


def test_the_move_screen_searches_an_album_to_stand_next_to(client):
    page = client.get("/move/?kind=album&id=41&near=cream").get_data(as_text=True)

    assert "Fresh Cream" in page and "Disraeli Gears" in page
    assert "how=after&amp;next_to=22" in page
    assert "Kind of Blue" not in page


def test_the_move_screen_shows_and_carries_out_a_move_next_to_an_album(client, store):
    page = client.get("/move/?kind=album&id=41&how=after&next_to=22").get_data(as_text=True)
    assert "Right after Cream — Disraeli Gears." in page
    assert "Also put The Jimi Hendrix Experience in Rock" in page

    answer = client.post("/move/", data={"kind": "album", "id": "41", "how": "after", "next_to": "22", "confirm_cluster": "1"})

    assert answer.status_code == 302
    assert _shelves(store)[2] == [21, 22, 41]
    assert _confirmed(store, 4) == 2


def test_a_move_next_to_an_album_on_no_shelf_is_refused(client):
    assert client.get("/move/?kind=album&id=41&how=after&next_to=42").status_code == 400
    assert client.post("/move/", data={"kind": "album", "id": "41", "how": "before", "next_to": "42"}).status_code == 400


def test_a_visitor_reads_why_but_gets_no_action(store):
    set_password(store.data_dir, "a long enough password")
    visitor = create_app(store.data_dir).test_client()

    page = visitor.get("/albums/41").get_data(as_text=True)

    assert "is proposed from the styles" in page
    assert "Choose a cluster" not in page
    assert "Or in Rock" not in page
    assert "Somewhere else" not in page


def test_a_cluster_further_down_the_styles_than_the_spots_offered_places_nothing(store):
    # Blues twice, then Rock, Folk and Jazz once each: three other clusters, of which two are offered.
    store.save(Cluster, [*store.load(Cluster), Cluster(4, "Folk", 3)])
    store.save(Style, [*store.load(Style), Style(4, "Folk Rock", 4)])
    albums = store.load(Album)
    next(a for a in albums if a.id == 41).style_ids = [2, 3, 4]
    next(a for a in albums if a.id == 42).style_ids = [2, 1]
    store.save(Album, albums)
    offered = {s.cluster_id for s in other_spots(store, 41, CONSTANTS)}
    assert len(offered) == 2
    not_offered = ({1, 2, 4} - offered).pop()
    before = _shelves(store)

    assert place_in_cluster(store, 41, not_offered, CONSTANTS, confirm=True) is None
    assert _shelves(store) == before
    assert _confirmed(store, 4) is None
