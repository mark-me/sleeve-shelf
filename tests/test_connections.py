"""Tests for the Connections screen: what ties artists together, and the screen that shows it."""

import re
from datetime import datetime

import pytest

from sleeve_shelf import create_app
from sleeve_shelf.alias_groups import family_suggestions
from sleeve_shelf.access import set_password
from sleeve_shelf.config import load_settings
from sleeve_shelf.covers import ARTIST_DIR, COVER_DIR, cover_name
from sleeve_shelf.domain import (
    Album,
    AliasGroup,
    Artist,
    ArtistClusterAssignment,
    ArtistEnrichment,
    Cabinet,
    Cluster,
    Credit,
    Placement,
    ReleaseEnrichment,
    ReleaseLabel,
    Shelf,
    Track,
    UnrelatedArtists,
)
from sleeve_shelf.network import MUSICIAN_ALBUMS, Link, Network, OnRecord, Point, Tie, TiedAlbum, build, network, on_the_record, song_key, songs_elsewhere, tied_albums, ties_of, way
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


@pytest.mark.parametrize(
    ("role", "parts"),
    [
        ("Piano", ("Piano",)),
        ("Tenor Saxophone [Uncredited], Liner Notes", ("Tenor Saxophone",)),
        ("Vocals, Arranged By", ("Vocals", "Arranged By")),
        ("Producer", ("Producer",)),
        ("Conductor", ("Conductor",)),
        ("Musical Director", ("Musical Director",)),
        ("Written-By", ()),
        ("Executive-Producer", ()),
        ("Reissue Producer", ()),
        ("Engineer [Recording], Mastered By", ()),
        ("Design, Photography By", ()),
    ],
)
def test_who_counts_as_on_the_record(role, parts):
    assert on_the_record(role) == parts


def _on_the_record():
    """Bud Powell on Charlie Parker's record, and Jerome Kern only as its writer."""
    artists = [
        Artist(1, "Charlie Parker", discogs_artist_id=101),
        Artist(2, "Bud Powell", discogs_artist_id=102),
        Artist(3, "Jerome Kern", discogs_artist_id=103),
        Artist(4, "Various", discogs_artist_id=194),
    ]
    albums = [
        Album(1, 1, "Massey Hall", release_id=1),
        Album(2, 2, "The Amazing", release_id=2),
        Album(3, 4, "Jazz Hits", release_id=3),
    ]
    releases = [
        ReleaseEnrichment(
            1, (), None, FETCHED, tracklist=(),
            credits=(
                Credit(102, "Bud Powell", "Piano"),
                Credit(102, "Bud Powell", "Arranged By", "A2"),
                Credit(103, "Jerome Kern", "Written-By", "A1"),
                Credit(999, "Charles Mingus", "Bass"),
                Credit(101, "Charlie Parker", "Alto Saxophone"),
            ),
        ),
        ReleaseEnrichment(2, (), None, FETCHED, tracklist=(), credits=()),
        # A compilation ties no one, by its credits either.
        ReleaseEnrichment(3, (), None, FETCHED, tracklist=(), credits=(Credit(101, "Charlie Parker", "Alto Saxophone"),)),
    ]
    return artists, albums, releases


def test_a_credit_on_an_album_ties_its_artist_to_the_one_credited():
    artists, albums, releases = _on_the_record()

    links = build(artists, albums, [], releases, [], []).links

    # Not the writer, not someone outside the collection, not the artist on its own record.
    assert [(link.one, link.other, link.ties) for link in links] == [(1, 2, (Tie.CREDIT,))]
    assert links[0].on_record == (OnRecord(1, "Massey Hall", 1, 2, "Bud Powell", ("Piano", "Arranged By")),)


def test_a_credit_shows_the_albums_it_is_on_from_both_sides():
    artists, albums, releases = _on_the_record()
    net = build(artists, albums, [], releases, [], [])
    entry = net.links[0].on_record[0]

    # Bud Powell's own record is no part of it, seen from either artist.
    from_parker = tied_albums(net.around(1), 1, artists, albums, releases)[0]
    assert from_parker.theirs == () and from_parker.mine == (TiedAlbum(1, (), (entry,)),)
    from_powell = tied_albums(net.around(2), 2, artists, albums, releases)[0]
    assert from_powell.theirs == (TiedAlbum(1, (), (entry,)),) and from_powell.mine == ()


def test_a_credit_counts_as_a_close_step_on_the_way():
    artists, albums, releases = _on_the_record()
    net = build(artists, albums, [], releases, [], [])

    _, (point, link) = way(net, 1, 2, set(Tie))
    assert point.artist_id == 2 and link.on_record
    assert way(net, 1, 2, set(Tie) - {Tie.CREDIT}) is None


def test_the_screen_says_who_is_on_which_record(tmp_path):
    store = JsonStore(tmp_path / "data")
    artists, albums, releases = _on_the_record()
    store.save(Artist, artists)
    store.save(Album, albums)
    store.save(ReleaseEnrichment, releases)
    client = create_app(tmp_path / "data").test_client()

    page = client.get("/connections/?artist=1").get_data(as_text=True)
    assert 'data-tie="credit" checked' in page and "On the record" in page
    assert "Massey Hall" in page and "Bud Powell: Piano, Arranged By" in page
    way_page = client.get("/connections/?artist=1&to=2").get_data(as_text=True)
    assert "Bud Powell: Piano, Arranged By &middot; Massey Hall" in way_page
    data = client.get("/connections/network.json").get_json()
    assert [1, 2, ["credit"], [], [["Bud Powell", "Piano, Arranged By", "Massey Hall"]], []] in data["links"]


def _on_labels():
    """Miles Davis and Art Blakey on Blue Note, Tom Waits on none, a compilation on it too."""
    artists = [Artist(1, "Miles Davis"), Artist(2, "Art Blakey"), Artist(3, "Tom Waits"), Artist(4, "Various", discogs_artist_id=194)]
    albums = [
        Album(1, 1, "Volume 1", release_id=1),
        Album(2, 1, "Kind Of Blue", release_id=2),
        Album(3, 2, "Moanin'", release_id=3),
        Album(4, 3, "Closing Time", release_id=4),
        Album(5, 4, "Jazz Hits", release_id=5),
    ]
    blue_note, none = ReleaseLabel(50, "Blue Note"), ReleaseLabel(99, "Not On Label (Tom Waits Self-released)")
    releases = [
        ReleaseEnrichment(1, (), None, FETCHED, tracklist=(), labels=(blue_note,)),
        ReleaseEnrichment(2, (), None, FETCHED, tracklist=(), labels=(ReleaseLabel(51, "Columbia"),)),
        ReleaseEnrichment(3, (), None, FETCHED, tracklist=(), labels=(blue_note,)),
        ReleaseEnrichment(4, (), None, FETCHED, tracklist=(), labels=(none,)),
        ReleaseEnrichment(5, (), None, FETCHED, tracklist=(), labels=(blue_note,)),
    ]
    return artists, albums, releases


def test_the_same_label_ties_two_artists_and_shows_the_albums_on_it():
    artists, albums, releases = _on_labels()

    net = build(artists, albums, [], releases, [], [])

    # Neither "Not On Label" nor a compilation ties anyone.
    assert [(link.one, link.other, link.ties, link.labels) for link in net.links] == [(1, 2, (Tie.LABEL,), ("Blue Note",))]
    tied = tied_albums(net.around(1), 1, artists, albums, releases)[0]
    assert tied.theirs == (TiedAlbum(3, labels=("Blue Note",)),)
    # Kind Of Blue came out on another label, so it is no part of it.
    assert tied.mine == (TiedAlbum(1, labels=("Blue Note",)),)


def test_a_label_left_out_ties_no_one_however_discogs_spells_it():
    artists, albums, releases = _on_labels()
    assert build(artists, albums, [], releases, [], []).links

    # Discogs tells labels of one name apart with a number.
    releases = [
        ReleaseEnrichment(r.release_id, (), None, FETCHED, tracklist=(), labels=tuple(ReleaseLabel(l.discogs_label_id, l.name + " (8)") for l in r.labels))
        for r in releases
    ]
    assert build(artists, albums, [], releases, [], [], ["Blue Note"]).links == ()


def _session_collection(tmp_path, albums_on=MUSICIAN_ALBUMS):
    """A bassist without an album on enough records of two artists to be a point; a member of the
    band and a producer on as many, who are not; Coltrane's page, and Miles' band."""
    store = JsonStore(tmp_path)
    store.save(Artist, [Artist(1, "Miles Davis", discogs_artist_id=101), Artist(2, "John Coltrane", discogs_artist_id=102)])
    store.save(ArtistEnrichment, [ArtistEnrichment(101, None, None, FETCHED, member_ids=(500,))])
    albums = [Album(i, 1 if i % 2 else 2, f"Album {i}", release_id=i) for i in range(1, albums_on + 1)]
    store.save(Album, albums)
    store.save(
        ReleaseEnrichment,
        [
            ReleaseEnrichment(
                album.id, (), None, FETCHED, tracklist=(), labels=(),
                credits=(Credit(900, "Paul Chambers (3)", "Bass"), Credit(500, "Band Member", "Drums"), Credit(800, "Teo Macero", "Producer")),
            )
            for album in albums
        ],
    )
    return store


def test_a_musician_on_enough_albums_is_a_point(tmp_path):
    shown = network(_session_collection(tmp_path))

    musicians = [point for point in shown.points if point.is_musician]
    assert [(p.artist_id, p.name, p.albums) for p in musicians] == [(-900, "Paul Chambers", MUSICIAN_ALBUMS)]
    # Not the member of the band, on his own band's albums, nor the producer.
    ties = {(link.one, link.other): link.ties for link in shown.links}
    assert ties[(-900, 1)] == (Tie.SESSION,) and ties[(-900, 2)] == (Tie.SESSION,)
    # So the two artists have a way between them through the musician.
    found = way(shown, 1, 2, set(Tie))
    assert [point.artist_id for point, _ in found] == [1, -900, 2]


def test_a_musician_on_too_few_albums_is_no_point(tmp_path):
    shown = network(_session_collection(tmp_path, MUSICIAN_ALBUMS - 1))

    assert not [point for point in shown.points if point.is_musician]


def test_the_connections_of_a_musician_have_no_artist_page(tmp_path):
    _session_collection(tmp_path / "data")
    client = create_app(tmp_path / "data").test_client()

    page = client.get("/connections/?artist=-900")
    assert page.status_code == 200
    assert "Connections of Paul Chambers" in page.text and "Musician without an album of their own" in page.text
    assert "on 5 albums" in page.text
    assert "/artists/-900" not in page.text
    # The albums he is on, under the artist they are by.
    assert re.search(r"Album 1</a>", page.text) and "Paul Chambers: Bass" in page.text
    # Around an artist: tied to him, without a page either; and the way through him.
    around = client.get("/connections/?artist=1").text
    assert 'href="/connections/?artist=-900"' in around and 'data-ties="session"' in around
    assert client.get("/connections/?artist=1&to=-900").status_code == 200
    assert "Paul Chambers" in client.get("/connections/?q=chambers").text


def test_the_labels_that_tie_no_artists_are_a_setting(tmp_path):
    store = JsonStore(tmp_path / "data")
    artists, albums, releases = _on_labels()
    store.save(Artist, artists)
    store.save(Album, albums)
    store.save(ReleaseEnrichment, releases)
    client = create_app(tmp_path / "data").test_client()
    assert network(store).links

    page = client.get("/settings/").text
    assert 'name="labels_left_out"' in page and "Music On Vinyl" in page
    form = {"base_width_cm": "0.5", "surcharge_180_gram_cm": "0.15", "surcharge_gatefold_cm": "0.2", "labels_left_out": "Blue Note\n\n  UMe  \n"}
    client.post("/settings/", data=form)

    assert load_settings(tmp_path / "data").labels_left_out == ["Blue Note", "UMe"]
    assert not network(store).links


def test_a_label_is_a_loose_step_on_the_way():
    shown = _network(
        Link(1, 2, (Tie.LABEL,), labels=("Blue Note",)),
        Link(1, 3, (Tie.MEMBER,)),
        Link(2, 3, (Tie.FAMILY,)),
    )

    assert [point.artist_id for point, _ in way(shown, 1, 2, set(Tie))] == [1, 3, 2]
    assert way(shown, 1, 2, {Tie.LABEL})[1][1].labels == ("Blue Note",)


def test_the_same_label_starts_switched_off_and_is_listed_when_asked_for(tmp_path):
    store = JsonStore(tmp_path / "data")
    artists, albums, releases = _on_labels()
    store.save(Artist, artists)
    store.save(Album, albums)
    store.save(ReleaseEnrichment, releases)
    client = create_app(tmp_path / "data").test_client()

    page = client.get("/connections/?artist=1").text
    assert '<input type="checkbox" data-tie="label" >' in page and 'id="tie-2"' not in page
    asked = client.get("/connections/?artist=1&ties=label").text
    assert '<input type="checkbox" data-tie="label" checked>' in asked
    assert 'id="tie-2"' in asked and "Label: Blue Note" in asked
    assert [1, 2, ["label"], [], [], ["Blue Note"]] in client.get("/connections/network.json").get_json()["links"]


def test_a_joint_billing_borrows_the_picture_of_an_artist_it_names(tmp_path):
    store = JsonStore(tmp_path / "data")
    store.save(
        Artist,
        [
            Artist(1, "Duke Ellington", discogs_artist_id=101),
            Artist(2, "John Coltrane", discogs_artist_id=102),
            Artist(3, "Duke Ellington & John Coltrane"),
            Artist(4, "Nobody & John Coltrane"),
            Artist(5, "Art Blakey", discogs_artist_id=105),
            Artist(6, "Art Blakey Quintet"),
        ],
    )
    store.save(Album, [Album(1, 3, "One")])
    # No stored picture of Ellington: the next one named lends its picture.
    coltrane, blakey = "https://i.discogs.com/coltrane.jpg", "https://i.discogs.com/blakey.jpg"
    store.save(ArtistEnrichment, [ArtistEnrichment(102, None, coltrane, FETCHED), ArtistEnrichment(105, None, blakey, FETCHED)])
    folder = tmp_path / "data" / COVER_DIR / ARTIST_DIR
    folder.mkdir(parents=True)
    (folder / cover_name(coltrane)).write_bytes(b"jpeg")

    rows = {a[0]: a[4:] for a in create_app(tmp_path / "data").test_client().get("/connections/network.json").get_json()["artists"]}

    own = f"/covers/{ARTIST_DIR}/{cover_name(coltrane)}"
    assert rows[2] == [own, False]
    assert rows[3] == [own, True] and rows[4] == [own, True]
    # Whom it names has no stored picture itself, so there is nothing to borrow.
    assert rows[6] == [None, False] and rows[1] == [None, False]


def _moondog(tmp_path):
    """Moondog and Moondog Jr., one name inside the other but not related; Jr. without a picture,
    Moondog with one; and both on one label, which is no matter of their names."""
    store = JsonStore(tmp_path)
    store.save(Artist, [Artist(1, "Moondog (2)", discogs_artist_id=101), Artist(2, "Moondog Jr.")])
    store.save(Album, [Album(1, 1, "Moondog", release_id=1), Album(2, 2, "Songs", release_id=2)])
    label = (ReleaseLabel(50, "Prestige"),)
    store.save(
        ReleaseEnrichment,
        [
            ReleaseEnrichment(1, (), None, FETCHED, tracklist=(), credits=(), labels=label),
            ReleaseEnrichment(2, (), None, FETCHED, tracklist=(), credits=(), labels=label),
        ],
    )
    picture = "https://i.discogs.com/moondog.jpg"
    store.save(ArtistEnrichment, [ArtistEnrichment(101, None, picture, FETCHED)])
    folder = tmp_path / COVER_DIR / ARTIST_DIR
    folder.mkdir(parents=True)
    (folder / cover_name(picture)).write_bytes(b"jpeg")
    return store


def test_the_owner_can_say_two_names_are_not_related(tmp_path):
    store = _moondog(tmp_path)
    client = create_app(tmp_path).test_client()
    assert network(store).links[0].ties == (Tie.BILLING, Tie.LABEL)
    assert [s.member_ids for s in family_suggestions(store)] == [(2,)]
    page = client.get("/connections/?artist=1").text
    assert ">Not related</button>" in page
    assert client.get("/connections/network.json").get_json()["artists"][1][4:] != [None, False]

    answer = client.post("/connections/unrelated", data={"artist": "1", "other": "2", "ties": "billing,label"})

    assert answer.headers["Location"] == "/connections/?artist=1&ties=billing,label"
    assert store.load(UnrelatedArtists) == [UnrelatedArtists(1, 2)]
    # Only what came from the name goes: no tie by it, no family, no borrowed picture.
    assert network(store).links[0].ties == (Tie.LABEL,)
    assert family_suggestions(store) == []
    assert client.get("/connections/network.json").get_json()["artists"][1][4:] == [None, False]
    page = client.get("/connections/?artist=1").text
    assert ">Not related</button>" not in page and "You said these are not related" in page and "Moondog Jr." in page

    # Said from either side, it is one pair; and it can be taken back.
    client.post("/connections/unrelated", data={"artist": "2", "other": "1"})
    assert store.load(UnrelatedArtists) == [UnrelatedArtists(1, 2)]
    client.post("/connections/unrelated", data={"artist": "2", "other": "1", "undo": "1"})
    assert store.load(UnrelatedArtists) == []
    assert network(store).links[0].ties == (Tie.BILLING, Tie.LABEL)


def test_only_the_owner_says_two_names_are_not_related(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEVE_SHELF_HTTP_LOGIN", "1")
    login._pages.clear()
    store = _moondog(tmp_path)
    app = create_app(tmp_path)
    set_password(app.config["DATA_DIR"], "a long and strong one")
    visitor = app.test_client()

    assert "Not related" not in visitor.get("/connections/?artist=1").text
    assert visitor.post("/connections/unrelated", data={"artist": "1", "other": "2"}).status_code != 302 or not store.exists(UnrelatedArtists)
    assert store.load(UnrelatedArtists) == []


def test_saying_two_names_are_not_related_needs_two_artists(tmp_path):
    _moondog(tmp_path)
    client = create_app(tmp_path).test_client()

    assert client.post("/connections/unrelated", data={"artist": "1", "other": "99"}).status_code == 400
    assert client.post("/connections/unrelated", data={"artist": "1", "other": "1"}).status_code == 400


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
    assert [1, "Miles Davis", 2, 1, None, False] in data["artists"]
    assert [1, 5, ["songs"], ["'Round Midnight"], [], []] in data["links"]


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
