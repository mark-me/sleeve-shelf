"""Tests for cluster shifts: a new purchase that makes an artist's styles point to another cluster."""

import pytest

from sleeve_shelf import create_app
from sleeve_shelf.collection import import_discogs_collection
from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    Cabinet,
    Cluster,
    EraBand,
    Placement,
    Shelf,
    Style,
    WidthConstants,
)
from sleeve_shelf.ingestion.discogs_csv import CollectionItem
from sleeve_shelf.ingestion.formats import parse_format
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.shifts import cluster_shifts

CONSTANTS = WidthConstants(0.5, 0.15, 0.2)


@pytest.fixture
def app(tmp_path):
    app = create_app(tmp_path / "data")
    store = JsonStore(tmp_path / "data")
    store.save(Cabinet, [Cabinet(1, "Kast")])
    store.save(Shelf, [Shelf(1, 1, "a")])
    store.save(EraBand, [])
    store.save(Cluster, [Cluster(1, "Slowcore", 1), Cluster(2, "Post-Punk", 2)])
    store.save(Style, [Style(1, "Slowcore", 1), Style(2, "Post-Punk", 2), Style(3, "New Wave", 2)])
    store.save(Artist, [Artist(1, "Low", start_year=1993), Artist(2, "Codeine", start_year=1989)])
    # Low was curated into Slowcore; Codeine's cluster is only a proposal.
    store.save(
        ArtistClusterAssignment,
        [ArtistClusterAssignment(1, 1, confirmed=True), ArtistClusterAssignment(2, 1)],
    )
    store.save(
        Album,
        [
            Album(1, 1, "I Could Live In Hope", release_id=11, style_ids=[1], original_release_year=1994),
            Album(2, 2, "Frigid Stars", release_id=21, style_ids=[1], original_release_year=1990),
        ],
    )
    store.save(Placement, [])
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _store(app):
    return JsonStore(app.config["DATA_DIR"])


def _item(release_id, artist, title):
    parsed = parse_format("LP, Album")
    return CollectionItem(release_id, artist, title, parsed.is_vinyl, parsed.tokens)


def _buy(app, style_ids):
    """Two new albums by Low arrive with a sync, and the enrichment gives them their styles."""
    store = _store(app)
    items = [
        _item(11, "Low", "I Could Live In Hope"),
        _item(21, "Codeine", "Frigid Stars"),
        _item(12, "Low", "Hey What"),
        _item(13, "Low", "Double Negative"),
    ]
    import_discogs_collection(store, items, CONSTANTS)
    albums = store.load(Album)
    for album in albums:
        if album.release_id in (12, 13):
            album.style_ids = list(style_ids)
            album.original_release_year = 2021
    store.save(Album, albums)


def test_a_purchase_is_only_weighed_for_an_artist_with_a_confirmed_cluster(app):
    store = _store(app)
    items = [
        _item(11, "Low", "I Could Live In Hope"),
        _item(21, "Codeine", "Frigid Stars"),
        _item(12, "Low", "Hey What"),
        _item(22, "Codeine", "The White Birch"),
        _item(31, "Bedhead", "WhatFunLifeWas"),
    ]

    import_discogs_collection(store, items, CONSTANTS)

    marks = {album.title: album.new_purchase for album in store.load(Album)}
    assert marks == {
        "I Could Live In Hope": False,
        "Frigid Stars": False,
        "Hey What": True,
        "The White Birch": False,
        "WhatFunLifeWas": False,
    }
    # Without styles there is nothing to weigh yet.
    assert cluster_shifts(store) == []


def test_a_purchase_whose_styles_point_elsewhere_is_a_shift(app):
    _buy(app, [2, 3])

    shifts = cluster_shifts(_store(app))

    assert [(s.artist_id, s.cluster_id, s.proposed_cluster_id) for s in shifts] == [(1, 1, 2)]
    assert len(shifts[0].album_ids) == 2


def test_a_purchase_in_line_with_the_cluster_is_no_shift(app):
    _buy(app, [1])

    assert cluster_shifts(_store(app)) == []


def test_an_artist_whose_cluster_never_agreed_with_its_styles_is_not_reported(app):
    store = _store(app)
    albums = store.load(Album)
    albums[0].style_ids = [2]
    store.save(Album, albums)
    assert cluster_shifts(store) == []

    # A purchase with the same styles changes nothing about where they point.
    _buy(app, [2])
    assert cluster_shifts(store) == []


def test_a_shift_waits_on_the_dashboard_and_the_artist_until_decided(app, client):
    _buy(app, [2, 3])

    dashboard = client.get("/dashboard/").text
    assert "1 artist a new purchase points to another cluster" in dashboard
    to_check = client.get("/artists/?show=attention").text
    assert "Low" in to_check and "new purchase points to Post-Punk" in to_check
    page = client.get("/artists/1").text
    assert "A new purchase points to another cluster" in page
    assert "Hey What, Double Negative" in page and "Keep in Slowcore" in page
    # Nothing moved by itself.
    assert _store(app).load(ArtistClusterAssignment)[0].cluster_id == 1

    client.post("/artists/1/shift/keep")

    store = _store(app)
    assert store.load(ArtistClusterAssignment)[0].cluster_id == 1
    assert cluster_shifts(store) == []
    assert "A new purchase points to another cluster" not in client.get("/artists/1").text
    assert "new purchase points" not in client.get("/dashboard/").text


def test_accepting_a_shift_moves_the_artist_to_the_other_cluster(app, client):
    _buy(app, [2, 3])

    client.post("/artists/1/shift/accept")

    store = _store(app)
    assignment = next(a for a in store.load(ArtistClusterAssignment) if a.artist_id == 1)
    assert (assignment.cluster_id, assignment.confirmed) == (2, True)
    assert cluster_shifts(store) == []
    # Without a shift the action does nothing.
    client.post("/artists/2/shift/accept")
    assert next(a for a in store.load(ArtistClusterAssignment) if a.artist_id == 2).cluster_id == 1
