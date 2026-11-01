"""Tests for showing a shelf and search results as a list or a grid of covers."""

import pytest

from sleeve_shelf.domain import Album, Artist, Cabinet, Cluster, Placement, Shelf
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.web.app import create_app


@pytest.fixture
def client(tmp_path):
    store = JsonStore(tmp_path / "data")
    store.save(Cluster, [Cluster(1, "Jazz", 0)])
    store.save(Artist, [Artist(1, "Miles Davis")])
    store.save(Album, [Album(1, 1, "Kind Of Blue", cover_url="https://i.discogs.com/a.jpg"), Album(2, 1, "Milestones")])
    store.save(Cabinet, [Cabinet(1, "Kast")])
    store.save(Shelf, [Shelf(1, 1, "a")])
    store.save(Placement, [Placement(1, 1, 0), Placement(2, 1, 1)])
    return create_app(tmp_path / "data").test_client()


@pytest.mark.parametrize("address", ["/browse?shelf=1", "/browse?q=miles"])
def test_a_shelf_and_search_results_can_switch(client, address):
    page = client.get(address).text
    assert 'data-browse-view-choice="list"' in page and 'data-browse-view-choice="grid"' in page
    assert "browse-view.js" in page and 'class="ss-card ss-album-rows"' in page
    # The script is in the head, so a page in the grid does not show as a list first.
    assert page.index("browse-view.js") < page.index("</head>")


def test_other_pages_do_not_switch(client):
    assert "browse-view.js" not in client.get("/albums/1").text
