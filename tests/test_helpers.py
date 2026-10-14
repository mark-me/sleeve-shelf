"""Tests for the small helpers shared across the layers."""

from sleeve_shelf.domain import Artist, find_by_id
from sleeve_shelf.web.context import parse_number


def test_an_item_is_found_by_its_id():
    artists = [Artist(1, "Tindersticks"), Artist(2, "Low")]

    assert find_by_id(artists, 2).name == "Low"
    assert find_by_id(artists, 3) is None
    assert find_by_id(artists, None) is None


def test_a_typed_number_may_have_a_decimal_comma():
    assert parse_number("0,5") == 0.5
    assert parse_number(" 42 ") == 42.0
    assert parse_number("") is None and parse_number("veel") is None
