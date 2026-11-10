"""Tests for reorganising: the plan of rounds and steps, and carrying it out in the app."""

import random
import re

import pytest

from sleeve_shelf.config import Settings
from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    Cabinet,
    Cluster,
    Placement,
    ProposedPlacement,
    Shelf,
    TargetPlacement,
)
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.shelving.proposal import generate_proposal
from sleeve_shelf.shelving.reorganising import rounds, running, start, step_key, stop, tick_off
from sleeve_shelf.sorting.reorganising import Situation, StepKind, carry_out, plan, to_move
from sleeve_shelf.web.app import create_app

CONSTANTS = Settings().width_constants


def _carried_out(situation: Situation):
    """Every round of the plan done in turn: the shelves at the end, and the most on the table."""
    rows = {shelf: list(row) for shelf, row in situation.rows.items()}
    table, aside = list(situation.table), list(situation.aside)
    most = len(table)
    planned = plan(situation)
    for round_ in planned:
        for step in round_:
            carry_out(rows, table, aside, step)
            most = max(most, len(table))
        assert table == [], "a round ends with an empty table"
    assert aside == []
    return rows, most, planned


def _situation(rows, target, size, room=None, **extra):
    widths = {album: 1.0 for row in [*rows.values(), *target.values()] for album in row}
    widths.update(extra.pop("widths", {}))
    room = room or {shelf: float(max(len(rows.get(shelf, [])), len(target.get(shelf, [])))) for shelf in {*rows, *target}}
    return Situation(rows=rows, target=target, widths=widths, room=room, table_size=size, **extra)


def test_albums_that_stay_in_order_are_not_touched():
    situation = _situation({1: [1, 2, 3], 2: [4, 5]}, {1: [1, 2, 3], 2: [4, 5]}, 10)

    assert to_move(situation) == set()
    assert plan(situation) == []


def test_only_the_album_out_of_order_on_its_shelf_moves():
    situation = _situation({1: [2, 1, 3]}, {1: [1, 2, 3]}, 10, room={1: 4.0})

    assert len(to_move(situation)) == 1
    rows, _, _ = _carried_out(situation)
    assert rows[1] == [1, 2, 3]


def test_two_full_shelves_swap_through_the_table():
    situation = _situation({1: [1, 2], 2: [3, 4]}, {1: [3, 4], 2: [1, 2]}, 2)

    rows, most, _ = _carried_out(situation)

    assert rows == {1: [3, 4], 2: [1, 2]}
    assert most <= 2


def test_when_the_table_is_not_enough_albums_are_set_aside_and_taken_back():
    situation = _situation({1: [1], 2: [2]}, {1: [2], 2: [1]}, 1)

    rows, most, planned = _carried_out(situation)

    kinds = [step.kind for round_ in planned for step in round_]
    assert StepKind.SET_ASIDE in kinds and StepKind.TAKE_BACK in kinds
    assert rows == {1: [2], 2: [1]} and most == 1


def test_an_album_without_a_place_is_fetched_and_one_left_out_is_kept_apart():
    situation = _situation({1: [1, 9]}, {1: [1, 5]}, 5, room={1: 3.0}, left_out=frozenset({9}))

    rows, _, planned = _carried_out(situation)

    steps = [step for round_ in planned for step in round_]
    assert any(s.kind == StepKind.TAKE and s.shelf_id is None and s.album_ids == (5,) for s in steps)
    assert any(s.kind == StepKind.LEAVE_OUT and s.album_ids == (9,) for s in steps)
    assert rows == {1: [1, 5]}


def test_an_album_is_put_after_the_album_it_follows():
    situation = _situation({1: [1, 3], 2: [2]}, {1: [1, 2, 3], 2: []}, 5, room={1: 3.0, 2: 1.0})

    _, _, planned = _carried_out(situation)

    put = next(step for round_ in planned for step in round_ if step.kind == StepKind.PUT)
    assert (put.shelf_id, put.after_album_id, put.album_ids) == (1, 1, (2,))


def test_rounds_end_with_an_empty_table_and_hold_at_most_a_table_full():
    rows = {shelf: list(range(shelf * 10, shelf * 10 + 6)) for shelf in range(1, 5)}
    everything = [album for row in rows.values() for album in row]
    target = {shelf: everything[(shelf - 1) * 6 : shelf * 6][::-1] for shelf in range(1, 5)}

    result, most, planned = _carried_out(_situation(rows, target, 4))

    assert result == target
    assert most <= 4
    assert len(planned) >= 24 // 4 - 1


@pytest.mark.parametrize("seed", range(25))
def test_any_layout_is_reached_within_the_table(seed):
    chance = random.Random(seed)
    albums = list(range(1, 61))
    widths = {album: chance.choice([0.5, 0.7, 1.0, 1.4]) for album in albums}
    rows = {shelf: [] for shelf in range(1, 7)}
    for album in albums:
        rows[chance.randint(1, 6)].append(album)
    shuffled = albums[:]
    chance.shuffle(shuffled)
    left_out = frozenset(shuffled[:5])
    target = {shelf: [] for shelf in range(1, 7)}
    for album in shuffled[5:]:
        target[chance.randint(1, 6)].append(album)
    room = {shelf: chance.uniform(4, 9) for shelf in rows}
    situation = Situation(rows, target, left_out, (), (), widths, room, chance.choice([1, 3, 8, 20]))

    result, most, _ = _carried_out(situation)

    assert {shelf: row for shelf, row in result.items() if row or target.get(shelf)} == {
        shelf: row for shelf, row in target.items() if row or result.get(shelf)
    }
    assert most <= situation.table_size


def test_a_step_that_does_not_fit_the_shelves_is_refused():
    from sleeve_shelf.sorting.reorganising import Step

    with pytest.raises(ValueError):
        carry_out({1: [1]}, [], [], Step(StepKind.TAKE, (2,), 1))
    with pytest.raises(ValueError):
        carry_out({1: [1]}, [5], [], Step(StepKind.PUT, (5,), 1, after_album_id=9))


# Carrying it out in the app


def _collection(tmp_path):
    """Two clusters on two shelves, every album standing on the shelf of the other cluster."""
    store = JsonStore(tmp_path)
    store.save(Cluster, [Cluster(1, "Jazz", 0), Cluster(2, "Rock", 1)])
    store.save(Artist, [Artist(1, "Miles Davis", start_year=1955), Artist(2, "Cream", start_year=1966)])
    store.save(ArtistClusterAssignment, [ArtistClusterAssignment(1, 1, True), ArtistClusterAssignment(2, 2, True)])
    store.save(
        Album,
        [Album(i, 1, f"Jazz {i}", original_release_year=1950 + i) for i in range(1, 5)]
        + [Album(i, 2, f"Rock {i}", original_release_year=1960 + i) for i in range(11, 15)],
    )
    store.save(Cabinet, [Cabinet(1, "Kast", position=0)])
    store.save(Shelf, [Shelf(1, 1, "a", width_cm=10.0, position=0), Shelf(2, 1, "b", width_cm=10.0, position=1)])
    store.save(
        Placement,
        [Placement(i, 1, n) for n, i in enumerate(range(11, 15))] + [Placement(i, 2, n) for n, i in enumerate(range(1, 5))],
    )
    return store


@pytest.fixture
def store(tmp_path):
    store = _collection(tmp_path / "data")
    generate_proposal(store, CONSTANTS, 0)
    return store


@pytest.fixture
def client(store):
    return create_app(store.data_dir).test_client()


def _shelves(store):
    rows: dict[int, list[int]] = {}
    for p in sorted(store.load(Placement), key=lambda p: (p.shelf_id, p.position)):
        rows.setdefault(p.shelf_id, []).append(p.album_id)
    return rows


def _to_the_end(store):
    for _ in range(100):
        remaining = rounds(store, CONSTANTS)
        if not remaining:
            return
        assert tick_off(store, step_key(remaining[0][0]), CONSTANTS)
    raise AssertionError("no end")


def test_starting_keeps_the_proposal_as_target_and_changes_no_shelf(store):
    before = _shelves(store)

    assert start(store, CONSTANTS)

    assert _shelves(store) == before
    assert store.load(TargetPlacement) and not store.exists(ProposedPlacement)
    reorganisation = running(store)
    # The calmer proposal keeps Rock where it stands: only Jazz moves.
    assert reorganisation.to_move == 4 and reorganisation.table_records == 50


def test_each_step_changes_the_layout_until_it_is_the_proposal(store):
    target = {}
    for p in sorted(store.load(ProposedPlacement), key=lambda p: (p.shelf_id, p.position)):
        target.setdefault(p.shelf_id, []).append(p.album_id)
    start(store, CONSTANTS)

    first = rounds(store, CONSTANTS)[0][0]
    assert tick_off(store, step_key(first), CONSTANTS)
    assert set(first.album_ids) <= set(running(store).on_table)
    _to_the_end(store)

    assert _shelves(store) == target
    assert running(store).moved == 4 and running(store).on_table == []


def test_a_step_shown_before_the_shelves_changed_is_not_done(store):
    start(store, CONSTANTS)
    first = rounds(store, CONSTANTS)[0][0]
    before = _shelves(store)

    assert not tick_off(store, "take:1:None:999", CONSTANTS)
    assert _shelves(store) == before
    assert tick_off(store, step_key(first), CONSTANTS)


def test_a_move_by_hand_meanwhile_is_taken_into_account(store):
    start(store, CONSTANTS)
    # By hand: one album stood where it goes before the plan gets to it.
    placements = store.load(Placement)
    target = {t.album_id: t for t in store.load(TargetPlacement)}
    moved = placements[0]
    moved.shelf_id = target[moved.album_id].shelf_id
    moved.position = -1
    store.save(Placement, placements)

    _to_the_end(store)

    assert all(_shelves(store)[t.shelf_id].count(t.album_id) == 1 for t in target.values())


def test_stopping_leaves_what_was_done(store):
    start(store, CONSTANTS)
    tick_off(store, step_key(rounds(store, CONSTANTS)[0][0]), CONSTANTS)
    after_one = _shelves(store)

    stop(store)

    assert running(store) is None and not store.exists(TargetPlacement)
    assert _shelves(store) == after_one


def test_the_screen_shows_a_step_and_ticks_it_off(client, store):
    assert "Reorganise: carry it out step by step" in client.get("/proposal/").text
    assert client.post("/reorganise/start").headers["Location"] == "/reorganise/"

    page = client.get("/reorganise/").text
    assert "Round 1" in page and "Take out of Kast › b" in page and "on the table" in page
    key = re.search(r'name="step" value="([^"]+)"', page).group(1)
    assert client.post("/reorganise/step", data={"step": key}).headers["Location"] == "/reorganise/"
    assert "/reorganise/?changed=1" == client.post("/reorganise/step", data={"step": key}).headers["Location"]
    assert "A reorganisation is running" in client.get("/dashboard/").text

    _to_the_end(store)
    assert "All done" in client.get("/reorganise/").text
    assert "ended" in client.post("/reorganise/stop", follow_redirects=True).text
    assert "Make a sorting proposal" in client.get("/reorganise/").text


def test_accepting_a_proposal_at_once_ends_a_reorganisation(client, store):
    start(store, CONSTANTS)
    generate_proposal(store, CONSTANTS, 0)

    client.post("/proposal/accept")

    assert running(store) is None and not store.exists(TargetPlacement)
