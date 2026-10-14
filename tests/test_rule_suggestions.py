"""Tests for location-rule suggestions: rules the layout as it stands hints at."""

import pytest

from sleeve_shelf import create_app
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
)
from sleeve_shelf.persistence import JsonStore


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


@pytest.fixture
def stored(app):
    """The fixture's collection standing on shelves: Low in Kast, Codeine in a second cabinet."""
    from sleeve_shelf.domain import LocationRule, LocationRuleTarget
    from sleeve_shelf.rule_suggestions import rule_suggestions

    store = _store(app)
    store.save(Cabinet, [Cabinet(1, "Kast"), Cabinet(2, "Externe kast"), Cabinet(3, "Koffer")])
    store.save(
        Shelf, [Shelf(1, 1, "a", width_cm=30), Shelf(2, 2, "x", width_cm=30), Shelf(3, 3, "k", width_cm=30)]
    )
    albums = store.load(Album)
    albums += [
        Album(3, 2, "The White Birch", release_id=22, style_ids=[1], original_release_year=1994),
        Album(4, 1, "Hey What", release_id=12, style_ids=[1], original_release_year=2021),
    ]
    store.save(Album, albums)
    return store, LocationRule, LocationRuleTarget, rule_suggestions


def _stand(store, places):
    store.save(
        Placement,
        [Placement(album_id, shelf_id, position) for position, (album_id, shelf_id) in enumerate(places)],
    )


def test_a_cluster_wholly_in_a_cabinet_two_away_from_the_proposal_gets_a_suggestion(stored):
    store, _rule, target, rule_suggestions = stored
    # Everything of Slowcore stands in Koffer; a proposal would start filling at Kast.
    _stand(store, [(1, 3), (2, 3), (3, 3), (4, 3)])

    suggestions = rule_suggestions(store)

    assert [(s.target_type, s.target_id, s.cabinet_id, s.album_count) for s in suggestions] == [
        (target.CLUSTER, 1, 3, 4)
    ]


def test_a_layout_that_merely_spills_into_the_next_cabinet_suggests_nothing(stored):
    store, _rule, _target, rule_suggestions = stored
    _stand(store, [(1, 2), (2, 2), (3, 2), (4, 2)])

    assert rule_suggestions(store) == []


def test_an_album_apart_from_the_rest_of_its_artist_gets_a_rule_of_its_own(stored):
    store, _rule, target, rule_suggestions = stored
    albums = store.load(Album)
    albums += [
        Album(5, 1, "Secret Name", release_id=13, style_ids=[1], original_release_year=1999),
        Album(6, 1, "Trust", release_id=14, style_ids=[1], original_release_year=2002),
    ]
    store.save(Album, albums)
    # Five Low albums in Kast, one box set in Koffer.
    albums.append(Album(7, 1, "Ones And Sixes", release_id=15, style_ids=[1], original_release_year=2015))
    store.save(Album, albums)
    _stand(store, [(1, 1), (4, 1), (5, 1), (6, 1), (7, 3)])

    suggestions = rule_suggestions(store)

    assert (target.ALBUM, 7, 3, 1) in [
        (s.target_type, s.target_id, s.cabinet_id, s.album_count) for s in suggestions
    ]


def test_an_existing_rule_or_a_cabinet_outside_the_sorting_needs_no_suggestion(stored):
    store, rule, target, rule_suggestions = stored
    _stand(store, [(1, 3), (2, 3), (3, 3), (4, 3)])
    store.save(rule, [rule(1, target.CLUSTER, 1, 2)])
    # A rule on the cluster covers its artists, whatever cabinet it names.
    assert rule_suggestions(store) == []

    store.save(rule, [])
    cabinets = store.load(Cabinet)
    cabinets[2].outside_sorting = True
    store.save(Cabinet, cabinets)
    assert rule_suggestions(store) == []


def test_suggestions_are_added_per_cabinet_only_when_accepted(stored, client, app):
    store, rule, target, _suggest = stored
    _stand(store, [(1, 3), (2, 3), (3, 3), (4, 3)])

    page = client.get("/rules/").text
    assert "Suggested from your layout" in page and "Slowcore" in page and "4 albums" in page
    assert "a proposal would put it in Kast" in page
    assert _store(app).load(rule) == []
    # The Dashboard and the menu say that something is waiting under Location rules.
    assert "1 location rule suggested from your layout" in client.get("/dashboard/").text

    response = client.post("/rules/suggestions/3/accept", follow_redirects=True)

    rules = _store(app).load(rule)
    assert [(r.target_type, r.target_id, r.cabinet_id, r.note) for r in rules] == [
        (target.CLUSTER, 1, 3, "Suggested from the layout")
    ]
    assert "1 rule added." in response.text
    assert "Suggested from your layout" not in client.get("/rules/").text


def test_a_suggestion_turned_down_is_not_made_again(stored, client, app):
    store, rule, _target, rule_suggestions = stored
    _stand(store, [(1, 3), (2, 3), (3, 3), (4, 3)])

    response = client.post("/rules/suggestions/3/dismiss", follow_redirects=True)

    assert "1 suggestion turned down" in response.text
    assert _store(app).load(rule) == []
    assert rule_suggestions(_store(app)) == []
    assert "suggested from your layout" not in client.get("/dashboard/").text
