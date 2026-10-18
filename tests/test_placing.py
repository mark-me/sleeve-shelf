"""Tests for moving albums by hand, rearranging shelves, and the location rules."""

import pytest

from sleeve_shelf.domain import (
    Album,
    Artist,
    Cabinet,
    LocationRule,
    LocationRuleTarget,
    Placement,
    PlacementSource,
    ProposedPlacement,
    Shelf,
)
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.placing import (
    ShelvesChanged,
    move_albums,
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

