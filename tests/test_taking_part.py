"""Tests for what takes part in the sorting: the albums sorted, the shelves filled."""

from sleeve_shelf.domain import (
    Album,
    Cabinet,
    FormatTokens,
    Placement,
    Shelf,
    ShelfType,
)
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.library.taking_part import albums_taking_part, kept_shelf_ids, usable_shelves

LP = FormatTokens(qualifiers=("LP", "Album"))
SINGLE = FormatTokens(qualifiers=('7"', "Single"))


def test_lps_take_part_and_a_single_only_once_it_stands_on_a_shelf(tmp_path):
    store = JsonStore(tmp_path)
    store.save(Album, [
        Album(1, 1, "LP", format_tokens=LP),
        Album(2, 1, "Single", format_tokens=SINGLE),
        Album(3, 1, "Single on a shelf", format_tokens=SINGLE),
        Album(4, 1, "Format unknown"),
    ])
    store.save(Placement, [Placement(3, 1, 0)])

    assert [album.id for album in albums_taking_part(store)] == [1, 3, 4]


def test_showcases_and_cabinets_outside_the_sorting_are_kept_and_shelves_without_width_skipped(tmp_path):
    store = JsonStore(tmp_path)
    store.save(Cabinet, [Cabinet(1, "Kast"), Cabinet(2, "Koffer", outside_sorting=True)])
    store.save(Shelf, [
        Shelf(1, 1, "a", 80.0),
        Shelf(2, 1, "b"),
        Shelf(3, 1, "toplader", 30.0, ShelfType.TOP_LOADER, is_showcase=True),
        Shelf(4, 2, "c", 80.0),
    ])

    assert kept_shelf_ids(store) == {3, 4}
    usable, skipped = usable_shelves(store)
    assert [s.id for s in usable] == [1] and [s.id for s in skipped] == [2, 3, 4]
