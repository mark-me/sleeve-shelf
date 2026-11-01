"""Tests for what one needs standing at the cabinet: finding an album and where it stands."""

import re

import pytest

from sleeve_shelf.access import set_password
from sleeve_shelf.domain import Album, Artist, Cabinet, Cluster, Placement, Shelf
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.web.app import create_app


@pytest.fixture
def client(tmp_path):
    store = JsonStore(tmp_path / "data")
    store.save(Cluster, [Cluster(1, "Jazz", 0)])
    store.save(Artist, [Artist(1, "Miles Davis")])
    store.save(Album, [Album(1, 1, "Kind Of Blue", release_id=7), Album(2, 1, "Unplaced One")])
    store.save(Cabinet, [Cabinet(1, "Kast")])
    store.save(Shelf, [Shelf(1, 1, "a")])
    store.save(Placement, [Placement(1, 1, 0)])
    return create_app(tmp_path / "data").test_client()


def test_an_album_says_first_where_it_stands_and_plays_from_there(client):
    page = client.get("/albums/1").text

    where = page[page.index("ss-album-where") : page.index("ss-tabs")]
    assert 'href="/browse?shelf=1#album-1"' in where and "Stands in Kast &middot; a" in where
    assert 'data-play-album="/albums/1/previews"' in where
    # On every tab.
    for tab in ("statistics", "manage"):
        assert "Stands in Kast &middot; a" in client.get(f"/albums/1?tab={tab}").text
    assert "Not on a shelf" in client.get("/albums/2").text
    assert "Where it stands" not in page


def test_what_is_seldom_looked_up_is_folded_away(client):
    page = client.get("/albums/1").text
    folded = page[page.index('<details class="ss-album-more">') : page.index("</details>")]
    assert "Format" in folded and "discogs.com/release/7" in folded
    assert "Sorted under" not in folded and "Sorted under" in page


def test_every_page_can_search_but_browse_keeps_its_own_field(client):
    for page in ("/albums/1", "/artists/1", "/layout/", "/dashboard/", "/connections/", "/unplaced"):
        assert re.search(r'class="ss-top-search" method="get" action="/browse"', client.get(page).text), page
    browse = client.get("/browse").text
    assert "ss-top-search" not in browse and "data-live-search" in browse
    assert "ss-top-search" not in client.get("/browse?q=miles").text
    assert "Kind Of Blue" in client.get("/browse?q=kind").text


def test_a_visitor_can_search_from_a_page_too(tmp_path, client):
    set_password(tmp_path / "data", "a long enough password")
    assert "ss-top-search" in create_app(tmp_path / "data").test_client().get("/albums/1").text


def test_there_is_no_search_before_there_is_a_collection(tmp_path):
    page = create_app(tmp_path / "empty").test_client().get("/setup/").text
    assert "ss-top-search" not in page


def test_a_row_opens_the_album_and_keeps_its_other_links(client):
    for address in ("/browse?shelf=1", "/browse?q=kind"):
        page = client.get(address).text
        assert 'class="ss-row ss-row-opens"' in page and 'href="/albums/1"' in page
    assert 'class="ss-row-place" href="/browse?shelf=1#album-1"' in client.get("/browse?q=kind").text


def test_the_notice_about_saving_can_be_put_away(client):
    page = client.get("/layout/").text
    assert 'data-put-away="layout-saved-notice"' in page and "data-put-away-button" in page
    assert "ss-reach" not in client.get("/browse?shelf=1").text
