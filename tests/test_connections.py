"""Tests for the Connections screen: what ties artists together, and the screen that shows it."""

import re
from datetime import datetime

import pytest

from sleeve_shelf import create_app
from sleeve_shelf.access import set_password
from sleeve_shelf.covers import ARTIST_DIR, COVER_DIR, cover_name
from sleeve_shelf.domain import (
    Album,
    AliasGroup,
    Artist,
    ArtistClusterAssignment,
    ArtistEnrichment,
    Cabinet,
    Cluster,
    Placement,
    ReleaseEnrichment,
    Shelf,
    Track,
)
from sleeve_shelf.network import Link, Network, Point, Tie, TiedAlbum, build, network, song_key, songs_elsewhere, tied_albums, ties_of, way
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.web import login

FETCHED = datetime(2026, 10, 26)


def _release(release_id: int, *titles: str) -> ReleaseEnrichment:
    return ReleaseEnrichment(
        release_id, (), None, FETCHED, tracklist=tuple(Track(f"A{i}", t) for i, t in enumerate(titles, 1))
    )


def _collection(tmp_path) -> JsonStore:
    """Miles Davis and his quintet (Discogs: a member), Chet Baker with his quartet (a family,
    and one name inside the other), Ella Fitzgerald sharing a song with Miles, and Tom Waits
    tied to no one."""
    store = JsonStore(tmp_path)
    store.save(Cluster, [Cluster(1, "Jazz", 0), Cluster(2, "Songwriters", 1)])
    store.save(AliasGroup, [AliasGroup(1, "Chet Baker")])
    store.save(
        Artist,
        [
            Artist(1, "Miles Davis", discogs_artist_id=101),
            Artist(2, "The Miles Davis Quintet", discogs_artist_id=102),
            Artist(3, "Chet Baker", alias_group_id=1),
            Artist(4, "Chet Baker Quartet", alias_group_id=1),
            Artist(5, "Ella Fitzgerald"),
            Artist(6, "Tom Waits"),
        ],
    )
    store.save(ArtistClusterAssignment, [ArtistClusterAssignment(1, 1, True), ArtistClusterAssignment(6, 2, True)])
    store.save(
        ArtistEnrichment,
        [ArtistEnrichment(101, None, None, FETCHED, group_ids=(102, 999))],
    )
    store.save(
        Album,
        [
            Album(11, 1, "Round About Midnight", release_id=1),
            Album(12, 1, "Kind of Blue", release_id=2),
            Album(21, 2, "Relaxin'", release_id=3),
            Album(31, 3, "Chet"),
            Album(41, 4, "Quartet"),
            Album(51, 5, "Ella Sings", release_id=5),
            Album(61, 6, "Closing Time", release_id=6),
        ],
    )
    store.save(
        ReleaseEnrichment,
        [
            _release(1, "'Round Midnight", "Intro"),
            _release(2, "So What", "All Blues"),
            _release(3, "If I Were A Bell"),
            _release(5, "Round Midnight (Live)", "Summertime", "Intro"),
            _release(6, "Martha", "Intro"),
        ],
    )
    return store


def _ties(net) -> dict[tuple[int, int], tuple[Tie, ...]]:
    return {(link.one, link.other): link.ties for link in net.links}


def test_songs_are_compared_without_brackets_accents_punctuation_or_a_leading_the():
    assert song_key("'Round Midnight (Take 2)") == "round midnight"
    assert song_key("Round  Midnight [Live]") == "round midnight"
    assert song_key("Café Bleu") == "cafe bleu"
    assert song_key("The Girl From Ipanema") == "girl from ipanema"
    # Only brackets at the end fall away: at the start they are part of the title.
    assert song_key("( Dance With The ) Guitar Man") == "dance with the guitar man"
    assert song_key("Round Midnight (Take 2) [Bonus]") == "round midnight"
    assert song_key("(Nice Dream)") == "nice dream"


def _songs_by(*albums: tuple[int, str, tuple[int, ...] | None]):
    """Artists 1, 2, … each with one album holding one song, by the writers given."""
    artists = [Artist(i, f"Artist {i}") for i in range(1, len(albums) + 1)]
    records = [Album(i, i, f"Album {i}", release_id=i) for i in range(1, len(albums) + 1)]
    releases = [
        ReleaseEnrichment(i, (), None, FETCHED, tracklist=(Track("A1", title, None, writers),))
        for i, (_, title, writers) in enumerate(albums, 1)
    ]
    return {(link.one, link.other): link.songs for link in build(artists, records, [], releases, [], []).links}


def test_a_title_by_other_writers_is_another_song():
    kern, rose = (11,), (21,)

    # Bud Powell and Ella have Kern's; Guns N' Roses has a song of its own by that name.
    assert _songs_by((1, "Yesterdays", kern), (2, "Yesterdays", kern), (3, "Yesterdays", rose)) == {(1, 2): ("Yesterdays",)}
    # Tracks that share one writer of several are one song, also through a third.
    assert set(_songs_by((1, "Song", (1,)), (2, "Song", (1, 2)), (3, "Song", (2,)))) == {(1, 2), (1, 3), (2, 3)}


def test_a_song_without_its_writers_counts_when_its_title_is_one_song():
    kern, rose = (11,), (21,)

    # Every track with writers is Kern's: one without them is taken for his too.
    assert set(_songs_by((1, "Yesterdays", kern), (2, "Yesterdays", kern), (3, "Yesterdays", ()))) == {(1, 2), (1, 3), (2, 3)}
    # Two songs of that title: one without writers could be either, so it ties no one.
    assert _songs_by((1, "Yesterdays", kern), (2, "Yesterdays", kern), (3, "Yesterdays", rose), (4, "Yesterdays", None)) == {(1, 2): ("Yesterdays",)}
    # No writers known at all, as before a fetch run brought them: the title decides.
    assert set(_songs_by((1, "Yesterdays", None), (2, "Yesterdays", ()))) == {(1, 2)}


def test_the_albums_of_a_tie_are_those_with_the_same_song():
    artists = [Artist(1, "Bud Powell"), Artist(2, "Guns N' Roses")]
    albums = [Album(1, 1, "Jazz Giant", release_id=1), Album(2, 2, "Greatest Hits", release_id=2), Album(3, 2, "Covers", release_id=3)]
    releases = [
        ReleaseEnrichment(1, (), None, FETCHED, tracklist=(Track("A1", "Yesterdays", None, (11,)), Track("A2", "Tea", None, (5,)))),
        ReleaseEnrichment(2, (), None, FETCHED, tracklist=(Track("A1", "Yesterdays", None, (21,)),)),
        ReleaseEnrichment(3, (), None, FETCHED, tracklist=(Track("A1", "Tea", None, (5,)),)),
    ]
    net = build(artists, albums, [], releases, [], [])

    tied = tied_albums(net.around(1), 1, artists, albums, releases)

    # Tied by "Tea" alone: their "Yesterdays" is another song, so its album is not shown.
    assert [t.theirs for t in tied] == [(TiedAlbum(3, ("Tea",)),)]
    assert tied[0].mine == (TiedAlbum(1, ("Tea",)),)


def test_a_compilation_shares_no_song():
    artists = [Artist(1, "Miles Davis"), Artist(2, "Various", discogs_artist_id=194), Artist(3, "Bill Evans")]
    albums = [Album(1, 1, "One", release_id=1), Album(2, 2, "Jazz Hits", release_id=2), Album(3, 3, "Two", release_id=3)]
    releases = [_release(1, "So What"), _release(2, "So What", "Waltz For Debby"), _release(3, "Waltz For Debby")]

    assert build(artists, albums, [], releases, [], []).links == ()


def test_each_kind_of_tie_is_found(tmp_path):
    net = network(_collection(tmp_path))

    assert _ties(net) == {
        # Discogs lists the quintet among Miles' groups, and his name is inside its name.
        (1, 2): (Tie.MEMBER, Tie.BILLING),
        # A family, and one name inside the other.
        (3, 4): (Tie.BILLING, Tie.FAMILY),
        (1, 5): (Tie.SONGS,),
    }
    songs = next(link for link in net.links if (link.one, link.other) == (1, 5)).songs
    # The title as first found; "Intro" ties no one, so Tom Waits stays on his own.
    assert songs == ("'Round Midnight",)


def test_a_band_is_a_tie_whichever_record_names_the_other(tmp_path):
    store = _collection(tmp_path)
    store.save(ArtistEnrichment, [ArtistEnrichment(102, None, None, FETCHED, member_ids=(101,))])

    assert _ties(network(store))[(1, 2)] == (Tie.MEMBER, Tie.BILLING)


def test_the_closest_ties_come_first_around_an_artist(tmp_path):
    net = network(_collection(tmp_path))

    around = net.around(1)

    assert [point.name for point, _ in around] == ["The Miles Davis Quintet", "Ella Fitzgerald"]
    assert net.around(6) == []
    # Each artist with its albums and cluster; the clusters in their order on the shelves.
    miles = next(point for point in net.points if point.artist_id == 1)
    assert (miles.albums, miles.cluster_id) == (2, 1)
    assert net.clusters == ((1, "Jazz"), (2, "Songwriters"))


def test_an_artist_only_on_albums_of_its_own_shares_no_song_with_itself():
    artists = [Artist(1, "Miles Davis")]
    albums = [Album(1, 1, "One", release_id=1), Album(2, 1, "Two", release_id=2)]
    releases = [_release(1, "So What"), _release(2, "So What")]

    assert build(artists, albums, [], releases, [], []).links == ()


def test_a_tie_comes_with_the_albums_to_take_from_the_shelf(tmp_path):
    store = _collection(tmp_path)

    tied = {t.point.artist_id: t for t in ties_of(store, network(store), 1)}

    # A band: all of its albums.
    assert tied[2].theirs == (TiedAlbum(21),) and tied[2].mine == ()
    # A song: on each side the albums that have it, as each titles it.
    assert tied[5].theirs == (TiedAlbum(51, ("Round Midnight (Live)",)),)
    assert tied[5].mine == (TiedAlbum(11, ("'Round Midnight",)),)


def test_a_band_that_shares_a_song_shows_all_its_albums(tmp_path):
    store = _collection(tmp_path)
    store.save(Album, store.load(Album) + [Album(22, 2, "Workin'", release_id=7)])
    store.save(ReleaseEnrichment, store.load(ReleaseEnrichment) + [_release(7, "So What")])

    quintet = next(t for t in ties_of(store, network(store), 1) if t.point.artist_id == 2)

    assert quintet.link.ties == (Tie.MEMBER, Tie.BILLING, Tie.SONGS)
    assert set(quintet.theirs) == {TiedAlbum(21), TiedAlbum(22, ("So What",))}
    assert quintet.mine == (TiedAlbum(12, ("So What",)),)


def _network(*links: Link) -> Network:
    ids = sorted({i for link in links for i in (link.one, link.other)} | {9})
    return Network(tuple(Point(i, f"Artist {i}", 1, None) for i in ids), links, ())


def test_the_way_goes_by_close_ties_rather_than_a_song():
    shown = _network(
        Link(1, 2, (Tie.SONGS,), ("Summertime",)),
        Link(1, 3, (Tie.MEMBER,)),
        Link(2, 3, (Tie.FAMILY,)),
    )

    found = way(shown, 1, 2, set(Tie))

    # Two close steps weigh less than one song.
    assert [point.artist_id for point, _ in found] == [1, 3, 2]
    assert [link.ties if link else None for _, link in found] == [None, (Tie.MEMBER,), (Tie.FAMILY,)]
    # With those switched off, the song is the way.
    by_song = way(shown, 1, 2, {Tie.SONGS})
    assert [point.artist_id for point, _ in by_song] == [1, 2] and by_song[1][1].songs == ("Summertime",)


def test_a_way_names_only_the_ties_switched_on_and_may_not_exist():
    shown = _network(Link(1, 2, (Tie.MEMBER, Tie.SONGS), ("So What",)))

    _, (_, link) = way(shown, 1, 2, {Tie.MEMBER})
    assert link.ties == (Tie.MEMBER,) and link.songs == ()
    # Artist 9 is tied to no one; one step is no way at all.
    assert way(shown, 1, 9, set(Tie)) is None
    assert way(shown, 1, 2, {Tie.FAMILY}) is None
    assert [p.artist_id for p, _ in way(shown, 1, 1, set(Tie))] == [1]


def test_an_albums_songs_elsewhere_in_the_collection(tmp_path):
    store = _collection(tmp_path)

    found = songs_elsewhere(11, store.load(Artist), store.load(Album), store.load(ReleaseEnrichment))

    # Its own title for the song; "Intro" counts for nothing.
    assert found == [("'Round Midnight", (51,))]
    assert songs_elsewhere(12, store.load(Artist), store.load(Album), store.load(ReleaseEnrichment)) == []


@pytest.fixture
def client(tmp_path):
    _collection(tmp_path / "data")
    return create_app(tmp_path / "data").test_client()


def test_the_screen_shows_the_ties_of_an_artist_as_a_list(client):
    page = client.get("/connections/?artist=1").get_data(as_text=True)

    assert "Connections of Miles Davis" in page
    assert "The Miles Davis Quintet" in page
    assert 'data-ties="member billing"' in page
    assert "&#39;Round Midnight" in page
    # The network is drawn by the vendored library, within the policy.
    assert "vendor/cytoscape.min.js" in page
    assert 'id="__________cytoscape_stylesheet"' in page


def test_the_list_says_where_the_albums_of_a_tie_stand(tmp_path):
    store = _collection(tmp_path / "data")
    store.save(Cabinet, [Cabinet(1, "Kast")])
    store.save(Shelf, [Shelf(1, 1, "c")])
    store.save(Placement, [Placement(51, 1, 0)])
    page = create_app(tmp_path / "data").test_client().get("/connections/?artist=1").get_data(as_text=True)

    # Ella's album with the song, on its shelf; Miles' own album with it, on none yet.
    assert 'href="/browse?shelf=1#album-51">Ella Sings</a>' in page
    assert "Kast &middot; c" in page
    assert 'href="/unplaced#album-11">Round About Midnight</a>' in page
    assert "Round Midnight (Live)" in page


def test_the_network_comes_with_full_screen_a_legend_and_a_way_to_the_middle(client):
    page = client.get("/connections/?artist=1").get_data(as_text=True)

    # The script fills the legend and offers the artist tapped; without it they stay hidden.
    assert "data-network-full" in page and "Full screen" in page
    assert "data-network-legend" in page
    assert re.search(r'<a [^>]*data-network-centre hidden>Put in the middle</a>', page)
    assert 'data-centre-url="/connections/?artist=0"' in page


def test_the_switches_go_along_in_the_links_once_switched(client):
    page = client.get("/connections/?artist=1&ties=member,family").get_data(as_text=True)

    assert '<input type="checkbox" data-tie="member" checked>' in page
    assert '<input type="checkbox" data-tie="songs" >' in page
    # On to another artist, the whole collection and the search: the same switches.
    assert 'href="/connections/?artist=2&amp;ties=member,family"' in page
    assert 'href="/connections/?ties=member,family"' in page
    assert '<input type="hidden" name="ties" value="member,family">' in page
    # Not switched yet: the links carry nothing, so each page starts with its defaults.
    plain = client.get("/connections/?artist=1").get_data(as_text=True)
    assert 'href="/connections/?artist=2"' in plain and 'name="ties"' not in plain


def test_a_ties_albums_are_folded_away_under_their_count(client):
    page = client.get("/connections/?artist=1").get_data(as_text=True)

    # Ella: her album with the song and Miles' own.
    ella = page[page.index('id="tie-5"'):]
    assert re.search(r"<details [^>]*data-tie-albums>\s*<summary>2 albums</summary>", ella)


def test_the_screen_finds_the_way_to_another_artist(client):
    # First the artists matching what was typed, the artist itself left out.
    found = client.get("/connections/?artist=2&way=ella").get_data(as_text=True)
    assert 'href="/connections/?artist=2&amp;to=5#way"' in found

    page = client.get("/connections/?artist=2&to=5").get_data(as_text=True)

    # The quintet, Miles by a band, Ella by a song; the network shows only the way.
    assert "From The Miles Davis Quintet to Ella Fitzgerald" in page and "2 steps" in page
    assert 'data-way="2,1,5"' in page
    steps = page[page.index('class="ss-card ss-way'):]
    assert steps.index("The Miles Davis Quintet") < steps.index("Miles Davis</a>") < steps.index("Ella Fitzgerald")
    # Instead of the list of ties.
    assert "Tied to The Miles Davis Quintet" not in page


def test_no_way_is_said_and_an_unknown_artist_is_not_found(client):
    page = client.get("/connections/?artist=1&to=6").get_data(as_text=True)

    assert "No way leads from Miles Davis to Tom Waits" in page
    # Without the songs, Ella is out of reach too.
    assert "No way leads" in client.get("/connections/?artist=1&to=5&ties=member,family").get_data(as_text=True)
    assert client.get("/connections/?artist=1&to=99").status_code == 404
    assert client.get("/connections/?to=5").status_code == 404


def test_an_albums_page_shows_its_songs_elsewhere_and_its_connections(client):
    page = client.get("/albums/11").get_data(as_text=True)

    assert 'href="/connections/?artist=1"' in page
    assert "The same songs elsewhere" in page
    assert 'href="/albums/51">Ella Fitzgerald — Ella Sings</a>' in page
    # An album none of whose songs is elsewhere has no such part.
    assert "The same songs elsewhere" not in client.get("/albums/12").get_data(as_text=True)


def test_an_artist_tied_to_no_one_says_so(client):
    page = client.get("/connections/?artist=6").get_data(as_text=True)

    assert "Nothing ties this artist to another" in page
    assert client.get("/connections/?artist=99").status_code == 404


def test_the_screen_finds_an_artist_to_put_in_the_middle(client):
    page = client.get("/connections/?q=chet").get_data(as_text=True)

    assert "/connections/?artist=3" in page and "/connections/?artist=4" in page
    assert "/connections/?artist=1" not in page
    assert "No artist matches" in client.get("/connections/?q=nobody").get_data(as_text=True)


def test_on_the_whole_collection_the_same_song_starts_switched_off(client):
    whole = client.get("/connections/").get_data(as_text=True)
    around = client.get("/connections/?artist=1").get_data(as_text=True)

    assert '<input type="checkbox" data-tie="songs" >' in whole
    assert '<input type="checkbox" data-tie="songs" checked>' in around


def test_the_network_comes_as_compact_lists(client):
    data = client.get("/connections/network.json").get_json()

    assert data["clusters"] == [[1, "Jazz"], [2, "Songwriters"]]
    assert [1, "Miles Davis", 2, 1, None] in data["artists"]
    assert [1, 5, ["songs"], ["'Round Midnight"]] in data["links"]


def test_the_network_draws_only_pictures_kept_with_the_app(tmp_path):
    store = _collection(tmp_path / "data")
    artists = store.load(Artist)
    artists[4] = Artist(5, "Ella Fitzgerald", discogs_artist_id=105)
    artists[5] = Artist(6, "Tom Waits", discogs_artist_id=106)
    store.save(Artist, artists)
    ella, waits = "https://i.discogs.com/ella.jpg", "https://i.discogs.com/waits.jpg"
    store.save(
        ArtistEnrichment,
        [ArtistEnrichment(105, None, ella, FETCHED), ArtistEnrichment(106, None, waits, FETCHED)],
    )
    folder = tmp_path / "data" / COVER_DIR / ARTIST_DIR
    folder.mkdir(parents=True)
    (folder / cover_name(ella)).write_bytes(b"jpeg")

    pictures = {a[0]: a[4] for a in create_app(tmp_path / "data").test_client().get("/connections/network.json").get_json()["artists"]}

    # Ella's picture is stored; Tom Waits' is still at Discogs, which a canvas cannot draw.
    assert pictures[5] == f"/covers/{ARTIST_DIR}/{cover_name(ella)}"
    assert pictures[6] is None


def test_the_tab_stands_next_to_browse_and_an_artists_page_links_to_it(client):
    assert 'href="/connections/"' in client.get("/browse").get_data(as_text=True)
    assert 'href="/connections/?artist=1"' in client.get("/artists/1").get_data(as_text=True)


def test_a_visitor_may_look_at_the_connections(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEVE_SHELF_HTTP_LOGIN", "1")
    login._pages.clear()
    _collection(tmp_path / "data")
    app = create_app(tmp_path / "data")
    set_password(app.config["DATA_DIR"], "a long and strong one")
    visitor = app.test_client()

    assert visitor.get("/connections/?artist=1").status_code == 200
    assert visitor.get("/connections/network.json").status_code == 200
    menu = visitor.get("/browse").get_data(as_text=True)
    assert 'href="/connections/"' in menu
    # The family on an artist's page is the owner's screen; a visitor sees its name only.
    artist = visitor.get("/artists/3").get_data(as_text=True)
    assert "/families/" not in artist
    # The family's name in its own place, not only in the heading (the artist has the same name).
    assert re.search(r"Family:\s*Chet Baker\s*&middot;", artist)
