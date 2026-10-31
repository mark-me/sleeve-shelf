"""Tests for the figures: an artist's page in two tabs, and the Statistics screen."""

from datetime import date, datetime

import pytest

from sleeve_shelf.web.app import create_app
from sleeve_shelf.access import set_password
from sleeve_shelf.insights.collection_stats import album_figures, artist_figures, collection_figures, from_the_shelf
from sleeve_shelf.domain import (
    Album,
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
    Style,
    Track,
)
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.web import login

FETCHED = datetime(2026, 10, 30)


def _release(release_id, credits=(), labels=(), songs=()):
    return ReleaseEnrichment(
        release_id, (), None, FETCHED,
        tracklist=tuple(Track(f"A{i}", title, None, ()) for i, title in enumerate(songs, 1)),
        credits=tuple(credits), labels=tuple(labels),
    )


def _collection(tmp_path) -> JsonStore:
    """Miles Davis with three albums, a bassist without an album of his own on all of them and
    on Coltrane's; Coltrane also on one of Miles'; a compilation that counts for no one.
    """
    store = JsonStore(tmp_path)
    store.save(Cluster, [Cluster(1, "Jazz", 0)])
    store.save(
        Artist,
        [
            Artist(1, "Miles Davis", discogs_artist_id=101, start_year=1945),
            Artist(2, "John Coltrane", discogs_artist_id=102),
            Artist(3, "Various", discogs_artist_id=194),
            Artist(4, "Tom Waits"),
        ],
    )
    store.save(ArtistClusterAssignment, [ArtistClusterAssignment(1, 1, True)])
    store.save(Style, [Style(1, "Modal", 1), Style(2, "Hard Bop", 1), Style(3, "Cool Jazz", 1)])
    store.save(
        Album,
        [
            Album(1, 1, "Kind Of Blue", release_id=1, original_release_year=1959, style_ids=[1, 2], manual_width_cm=1.0),
            Album(2, 1, "Milestones", release_id=2, original_release_year=1958, style_ids=[2], manual_width_cm=2.0),
            Album(3, 1, "Bitches Brew", release_id=3, original_release_year=1970, style_ids=[3]),
            Album(4, 2, "Giant Steps", release_id=4, original_release_year=1960, style_ids=[2]),
            Album(5, 3, "Jazz Hits", release_id=5),
        ],
    )
    chambers = Credit(900, "Paul Chambers (3)", "Bass")
    blue_note = ReleaseLabel(50, "Blue Note", "BLP 1")
    store.save(
        ReleaseEnrichment,
        [
            _release(1, [chambers, Credit(102, "John Coltrane", "Tenor Saxophone"), Credit(101, "Miles Davis", "Trumpet"), Credit(800, "Teo Macero", "Producer")], [blue_note], ["So What"]),
            _release(2, [chambers, Credit(800, "Teo Macero", "Producer")], [ReleaseLabel(51, "Columbia", "CL 1"), ReleaseLabel(52, "Not On Label (Miles Davis Self-released)")], ["Two Bass Hit"]),
            _release(3, [chambers, Credit(777, "Cover Man", "Design")]),
            _release(4, [chambers], [blue_note], ["So What"]),
            _release(5, [chambers], [blue_note], ["So What"]),
        ],
    )
    store.save(Cabinet, [Cabinet(1, "Kast")])
    store.save(Shelf, [Shelf(1, 1, "a"), Shelf(2, 1, "b")])
    store.save(Placement, [Placement(1, 1, 0), Placement(2, 2, 0)])
    return store


def test_an_artists_figures(tmp_path):
    figures = artist_figures(_collection(tmp_path), 1)

    assert figures.albums == 3 and figures.rank == 1 and not figures.rank_shared
    # What stands on a shelf only.
    assert figures.width_cm == 3.0 and figures.shelves == 2
    # An album counts for each of its styles, the most first.
    assert figures.styles == (("Hard Bop", 2), ("Cool Jazz", 1), ("Modal", 1))
    # Every year from the first to the last, so gaps show.
    assert figures.years[0] == (1958, 1) and figures.years[1] == (1959, 1) and figures.years[2] == (1960, 0)
    assert figures.years[-1] == (1970, 1)
    # On several albums, himself and those on one album left out; the producer counts here.
    assert [(p.name, len(p.album_ids), p.roles) for p in figures.companions] == [
        ("Paul Chambers", 3, ("Bass",)),
        ("Teo Macero", 2, ("Producer",)),
    ]
    assert figures.appears_on == ()


def test_an_artist_on_the_albums_of_others(tmp_path):
    figures = artist_figures(_collection(tmp_path), 2)

    assert [(entry.album_title, entry.roles) for entry in figures.appears_on] == [("Kind Of Blue", ("Tenor Saxophone",))]
    assert figures.rank == 2 and figures.shelves == 0


def test_the_collections_figures(tmp_path):
    figures = collection_figures(_collection(tmp_path))

    # No producer, no designer, no one on their own record, no compilation.
    assert [(p.name, p.artist_id, p.album_ids) for p in figures.sidemen] == [
        ("Paul Chambers", None, (1, 2, 3, 4)),
        ("John Coltrane", 2, (1,)),
    ]
    # On albums of two artists; a song of one artist, or from a compilation, is not listed.
    assert [(s.title, s.artists, s.album_ids) for s in figures.songs] == [("So What", 2, (1, 4))]
    # "Not On Label" is no label; a compilation has a label too.
    assert [(label.name, label.album_ids) for label in figures.labels] == [
        ("Blue Note", (1, 4, 5)),
        ("Columbia", (2,)),
    ]
    assert figures.credits_fetched and figures.labels_fetched


def test_who_holds_the_collection_together_and_the_longest_way(tmp_path):
    store = _collection(tmp_path)
    store.save(Artist, store.load(Artist) + [Artist(5, "Miles Davis Quintet"), Artist(6, "Miles Davis Quintet Live")])

    figures = collection_figures(store)

    # Close ties only: a credit counts, So What between Miles and Coltrane alone would not.
    # Miles: Coltrane by credit, and the two whose names hold his.
    assert [(hub.name, hub.ties) for hub in figures.hubs][:2] == [("Miles Davis", 3), ("Miles Davis Quintet", 2)]
    # Coltrane is two steps from each billing; Miles is between them.
    way = figures.longest_way
    assert way.steps == 2 and "John Coltrane" in (way.one_name, way.other_name)


def test_albums_per_decade_and_per_cluster(tmp_path):
    figures = collection_figures(_collection(tmp_path))

    # Every decade from the first to the last; the compilation has no year.
    assert figures.decades == ((1950, 2), (1960, 1), (1970, 1))
    assert figures.without_year == 1
    assert [(c.name, c.albums) for c in figures.clusters] == [("Jazz", 3), (None, 2)]


def test_something_from_the_shelf_is_the_same_all_day_until_another_is_asked_for(tmp_path):
    store = _collection(tmp_path)
    store.save(Album, store.load(Album) + [Album(6, 1, "On The Corner", original_release_year=1972)])
    day = date(2022, 5, 1)

    pick, long_ago = from_the_shelf(store, day)

    assert pick in (1, 2) and from_the_shelf(store, day)[0] == pick
    # Only what stands somewhere; from this year, fifty years ago.
    assert long_ago == (6,)
    assert {from_the_shelf(store, day, turn)[0] for turn in range(20)} == {1, 2}
    assert from_the_shelf(store, date(2000, 1, 1))[1] == ()


def test_a_member_of_the_band_is_no_sideman_on_its_albums(tmp_path):
    store = _collection(tmp_path)
    # Discogs lists the bassist as a member of Miles' band; he still counts on Coltrane's record.
    store.save(ArtistEnrichment, [ArtistEnrichment(101, None, None, FETCHED, member_ids=(900,))])

    sidemen = collection_figures(store).sidemen

    assert [(p.name, p.album_ids) for p in sidemen] == [("John Coltrane", (1,)), ("Paul Chambers", (4,))]


def test_a_sideman_with_a_point_of_his_own_leads_to_it(tmp_path):
    store = _collection(tmp_path)
    albums = store.load(Album)
    releases = store.load(ReleaseEnrichment)
    # Two more albums make five, and with that he is a point in the network.
    extra = [Album(i, 2, f"More {i}", release_id=i) for i in (7, 8)]
    store.save(Album, albums + extra)
    store.save(ReleaseEnrichment, releases + [_release(i, [Credit(900, "Paul Chambers (3)", "Bass")]) for i in (7, 8)])
    client = create_app(tmp_path).test_client()

    assert collection_figures(store).sidemen[0].point_id == -900
    assert 'href="/connections/?artist=-900"' in client.get("/statistics/").text
    assert 'href="/connections/?artist=-900"' in client.get("/artists/1").text


def test_the_figures_wait_for_the_fetch_run(tmp_path):
    store = _collection(tmp_path)
    store.save(ReleaseEnrichment, [ReleaseEnrichment(1, (), None, FETCHED, tracklist=())])
    client = create_app(tmp_path).test_client()

    assert not collection_figures(store).credits_fetched
    assert client.get("/statistics/").text.count("This comes with the next Discogs sync.") == 2


@pytest.fixture
def client(tmp_path):
    _collection(tmp_path / "data")
    return create_app(tmp_path / "data").test_client()


def test_the_page_of_an_artist_starts_with_what_it_is(client):
    page = client.get("/artists/1").text

    assert 'class="ss-tab active" href="/artists/1"' in page
    assert "Kind Of Blue" in page and "number 1 in your collection" in page
    assert "Hard Bop" in page and "ss-bar" in page and "Through the years" in page
    assert "Paul Chambers" in page
    # What can be changed is a tab further.
    assert 'name="start_year"' not in page and 'href="/artists/1?tab=manage"' in page


def test_managing_an_artist_is_a_tab_of_its_own(client):
    page = client.get("/artists/1?tab=manage").text

    assert 'name="start_year"' in page and "Location rules" in page and "Add picture" in page
    assert "Through the years" not in page
    # After saving, or an error, it stays there.
    saved = client.post("/artists/1", data={"start_year": "1945", "cluster_id": "1", "new_cluster": ""})
    assert saved.headers["Location"] == "/artists/1?tab=manage&saved=1"
    assert 'name="start_year"' in client.post("/artists/1", data={"start_year": "long ago", "cluster_id": ""}).text


def test_an_artist_with_few_albums_has_its_styles_as_labels(client):
    page = client.get("/artists/2").text

    assert "ss-bar-label" not in page and "Through the years" not in page
    assert '<span class="ss-chip me-1 mb-1 d-inline-block">Hard Bop</span>' in page
    assert "Also on" in page


def test_what_waits_for_the_owner_is_said_on_the_first_tab(client):
    # Coltrane has an album that is sorted and no cluster yet.
    page = client.get("/artists/2").text
    assert "This artist still needs something from you" in page
    assert "This artist still needs something from you" not in client.get("/artists/1").text
    # The list of artists leads straight to what needs doing.
    assert 'href="/artists/2?tab=manage"' in client.get("/artists/?q=coltrane").text


def test_a_visitor_sees_the_artist_and_no_tabs(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEVE_SHELF_HTTP_LOGIN", "1")
    login._pages.clear()
    _collection(tmp_path / "data")
    app = create_app(tmp_path / "data")
    set_password(app.config["DATA_DIR"], "a long and strong one")
    visitor = app.test_client()

    for address in ("/artists/1", "/artists/1?tab=manage"):
        page = visitor.get(address).text
        assert "Kind Of Blue" in page and "ss-tabs" not in page and 'name="start_year"' not in page
    assert "still needs something" not in visitor.get("/artists/2").text
    # The Statistics screen is the owner's.
    assert visitor.get("/statistics/").status_code != 200
    assert "/statistics/" not in visitor.get("/browse").text


def test_the_statistics_screen_opens_to_the_albums(client):
    page = client.get("/statistics/").text

    assert "Most on your records" in page and "Paul Chambers" in page
    assert "So What" in page and "By 2 artists" in page
    assert "Blue Note" in page
    assert "From the shelf today" in page and "?turn=1#today" in page
    assert "Who holds your collection together" in page and 'href="/connections/?artist=1"' in page
    assert "Per decade" in page and "1950s" in page and "Per cluster" in page and 'href="/artists/?cluster=1"' in page
    assert 'href="/albums/1">Miles Davis — Kind Of Blue</a>' in page and "Kast &middot; a" in page
    # A person who is an artist in the collection links to the page.
    assert 'href="/artists/2"' in page


def _album_figures_collection(tmp_path) -> JsonStore:
    store = JsonStore(tmp_path)
    store.save(Artist, [Artist(1, "Miles Davis", discogs_artist_id=101), Artist(2, "John Coltrane", discogs_artist_id=102)])
    store.save(Cluster, [Cluster(1, "Jazz", 0)])
    store.save(Style, [Style(1, "Modal", 1), Style(2, "Hard Bop", 1)])
    store.save(
        Album,
        [
            Album(1, 1, "Early", release_id=1, original_release_year=1955, style_ids=(2,)),
            Album(2, 1, "Kind Of Blue", release_id=2, original_release_year=1959, style_ids=(1, 2)),
            Album(3, 1, "Late", release_id=3, original_release_year=1970),
            Album(4, 2, "Giant Steps", release_id=4, original_release_year=1959, style_ids=(2,)),
            Album(5, 1, "No Year", release_id=5),
        ],
    )
    bass, drums = Credit(900, "Paul Chambers (3)", "Bass"), Credit(901, "Jimmy Cobb", "Drums")
    writer = Credit(800, "Bill Evans", "Written-By")
    store.save(
        ReleaseEnrichment,
        [
            ReleaseEnrichment(1, (), None, FETCHED, tracklist=(), credits=(bass, drums), labels=()),
            ReleaseEnrichment(
                2, (), None, FETCHED,
                tracklist=(Track("A1", "So What", "9:22", ()), Track("A2", "Blue In Green", "5:37", (800,))),
                credits=(bass, drums, Credit(102, "John Coltrane", "Tenor Saxophone"), Credit(101, "Miles Davis", "Trumpet"), writer, Credit(0, "Nobody", "Bass")),
                labels=(ReleaseLabel(50, "Columbia", "CS 8163"),),
            ),
            ReleaseEnrichment(3, (), None, FETCHED, tracklist=(Track("A1", "Untimed", None, ()),), credits=(bass,), labels=(ReleaseLabel(50, "Columbia"),)),
            ReleaseEnrichment(4, (), None, FETCHED, tracklist=(), credits=(), labels=(ReleaseLabel(60, "Not On Label (Miles Self-released)"),)),
        ],
    )
    return store


def test_the_figures_of_an_album(tmp_path):
    figures = album_figures(_album_figures_collection(tmp_path), 2)

    assert (figures.tracks, figures.minutes, figures.writers) == (2, 15, (("Bill Evans", 1),))
    assert (figures.position, figures.of_artist, figures.earlier, figures.later) == (2, 3, 1, 3)
    assert figures.same_year == (4,)
    assert figures.styles == (("Hard Bop", 3), ("Modal", 1))
    assert figures.labels == (("Columbia", 2, "CS 8163"),)
    # Not its own artist, not someone without a page on Discogs; an artist's own albums count.
    assert [(p.name, p.album_ids) for p in figures.people] == [
        ("Paul Chambers", (1, 2, 3)),
        ("Jimmy Cobb", (1, 2)),
        ("John Coltrane", (2, 4)),
    ]
    assert figures.people[2].artist_id == 2
    # Early has two of the same people; Late and Giant Steps only one.
    assert figures.alike == ((1, ("Paul Chambers", "Jimmy Cobb")),)


def test_an_album_with_little_known_has_figures_too(tmp_path):
    store = _album_figures_collection(tmp_path)

    figures = album_figures(store, 5)
    assert (figures.tracks, figures.minutes, figures.position, figures.earlier, figures.later) == (0, None, None, None, None)
    assert figures.people == () and figures.same_year == ()
    # One song without a length: no total that would be too short.
    assert album_figures(store, 3).minutes is None
    # A label that is no label does not count.
    assert album_figures(store, 4).labels == ()


def test_an_album_page_has_three_tabs_with_editing_apart(tmp_path):
    _album_figures_collection(tmp_path / "data")
    client = create_app(tmp_path / "data").test_client()

    album = client.get("/albums/2").text
    assert "Tracklist" in album and 'id="listen"' in album and "Who is on it" not in album and "Measured width" not in album
    assert 'href="/albums/2?tab=statistics"' in album and 'href="/albums/2?tab=manage"' in album

    figures = client.get("/albums/2?tab=statistics").text
    assert "Who is on it" in figures and "Paul Chambers" in figures and "With the same people" in figures
    assert 'href="/albums/1">Miles Davis — Early</a>' in figures and "Also from 1959" in figures
    assert 'href="/artists/2">John Coltrane</a>' in figures
    assert "Tracklist" not in figures and "Measured width" not in figures and 'id="listen"' not in figures

    manage = client.get("/albums/2?tab=manage").text
    assert "Measured width" in manage and "Location rules" in manage and "/move/" in manage
    assert "Tracklist" not in manage and "Who is on it" not in manage

    empty = client.get("/albums/5?tab=statistics").text
    assert "Nothing to tell about this album yet" in empty


def test_an_album_and_an_artist_link_to_discogs_when_linked(tmp_path):
    store = _album_figures_collection(tmp_path / "data")
    client = create_app(tmp_path / "data").test_client()

    for tab in ("", "?tab=statistics", "?tab=manage"):
        assert '<a href="https://www.discogs.com/release/2" target="_blank" rel="noopener">Discogs</a>' in client.get(f"/albums/2{tab}").text
    assert '<a href="https://www.discogs.com/artist/101" target="_blank" rel="noopener">Discogs</a>' in client.get("/artists/1").text

    store.save(Artist, [Artist(1, "Miles Davis"), Artist(2, "John Coltrane", discogs_artist_id=102)])
    albums = [Album(a.id, a.artist_id, a.title, original_release_year=a.original_release_year) for a in store.load(Album)]
    store.save(Album, albums)
    assert "discogs.com/artist" not in client.get("/artists/1").text
    assert "discogs.com/release" not in client.get("/albums/2").text
