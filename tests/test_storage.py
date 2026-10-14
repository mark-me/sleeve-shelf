"""Tests for managing the storage structure: cabinets and their shelves."""

import pytest

from sleeve_shelf.domain import Album, Artist, Cabinet, Placement, Shelf, ShelfLayer, ShelfType, in_order
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.storage import (
    StillInUse,
    move_cabinet,
    move_shelf,
    remove_cabinet,
    remove_shelf,
    save_cabinet,
    save_shelf,
)


@pytest.fixture
def store(tmp_path):
    return JsonStore(tmp_path)


def test_cabinets_are_added_at_the_end_and_can_be_changed_and_reordered(store):
    kast = save_cabinet(store, None, "Kast")
    koffer = save_cabinet(store, None, "Koffer", "Zolder", outside_sorting=True)

    assert [c.name for c in in_order(store.load(Cabinet))] == ["Kast", "Koffer"]
    assert (koffer.location, koffer.outside_sorting) == ("Zolder", True)

    save_cabinet(store, kast.id, "Kast links", "")
    move_cabinet(store, koffer.id, -1)

    cabinets = in_order(store.load(Cabinet))
    assert [(c.name, c.location) for c in cabinets] == [("Koffer", "Zolder"), ("Kast links", None)]


def test_shelves_are_added_to_their_cabinet_and_reordered_within_it(store):
    kast = save_cabinet(store, None, "Kast")
    a = save_shelf(store, kast.id, None, "a", width_cm=42.0, layer=ShelfLayer.TOP)
    b = save_shelf(store, kast.id, None, "b")

    assert move_shelf(store, b.id, -1) == kast.id
    assert [s.name for s in in_order(store.load(Shelf))] == ["b", "a"]

    save_shelf(store, kast.id, a.id, "a", type=ShelfType.TOP_LOADER, is_showcase=True)
    changed = next(s for s in store.load(Shelf) if s.id == a.id)
    assert (changed.width_cm, changed.layer, changed.is_showcase) == (None, None, True)


def test_only_a_top_loader_is_a_showcase(store):
    kast = save_cabinet(store, None, "Kast")
    with pytest.raises(ValueError):
        save_shelf(store, kast.id, None, "a", is_showcase=True)
    assert not store.exists(Shelf)


def test_only_what_is_empty_can_be_removed(store):
    kast = save_cabinet(store, None, "Kast")
    shelf = save_shelf(store, kast.id, None, "a")
    store.save(Artist, [Artist(1, "Tindersticks")])
    store.save(Album, [Album(1, 1, "Curtains")])
    store.save(Placement, [Placement(1, shelf.id, 0)])

    with pytest.raises(StillInUse):
        remove_cabinet(store, kast.id)
    with pytest.raises(StillInUse):
        remove_shelf(store, shelf.id)

    store.save(Placement, [])
    remove_shelf(store, shelf.id)
    remove_cabinet(store, kast.id)
    assert store.load(Shelf) == [] and store.load(Cabinet) == []


def test_an_unknown_cabinet_or_shelf_is_refused(store):
    with pytest.raises(LookupError):
        save_shelf(store, 9, None, "a")
    with pytest.raises(LookupError):
        remove_cabinet(store, 9)
