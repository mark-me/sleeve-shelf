"""Tests for album widths: estimated from the format, or measured by hand."""

import pytest

from sleeve_shelf.domain import Album, FormatTokens, WidthConstants
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.widths import apply_width_constants, set_measured_width

CONSTANTS = WidthConstants(0.5, 0.15, 0.2)


@pytest.fixture
def store(tmp_path):
    store = JsonStore(tmp_path)
    store.save(Album, [
        Album(1, 1, "Double", format_tokens=FormatTokens(disc_count=2, is_gatefold=True)),
        Album(2, 1, "Box", format_tokens=FormatTokens(disc_count=4, is_compound=True)),
    ])
    apply_width_constants(store, CONSTANTS)
    return store


def _album(store, album_id):
    return next(album for album in store.load(Album) if album.id == album_id)


def test_widths_follow_the_constants_and_a_box_awaits_a_measurement(store):
    assert (_album(store, 1).computed_width_cm, _album(store, 1).width_confirmed) == (1.2, True)
    assert _album(store, 2).width_confirmed is False

    apply_width_constants(store, WidthConstants(0.6, 0.15, 0.2))
    assert _album(store, 1).computed_width_cm == 1.4


def test_a_measured_width_settles_a_box_until_it_is_cleared(store):
    set_measured_width(store, 2, 3.5)
    assert (_album(store, 2).manual_width_cm, _album(store, 2).width_confirmed) == (3.5, True)
    # Estimating again leaves a measured width alone.
    apply_width_constants(store, CONSTANTS)
    assert _album(store, 2).width_confirmed is True

    set_measured_width(store, 2, None)
    assert (_album(store, 2).manual_width_cm, _album(store, 2).width_confirmed) == (None, False)
    with pytest.raises(ValueError):
        set_measured_width(store, 2, 0)


def test_without_albums_there_is_nothing_to_estimate(tmp_path):
    store = JsonStore(tmp_path)
    apply_width_constants(store, CONSTANTS)
    assert not store.exists(Album)
