"""Tests for reading config.yaml: a setting is read as its kind, whatever a hand wrote."""

import logging

from sleeve_shelf.config import CONFIG_FILE, Settings, load_settings
from sleeve_shelf.domain import Album, Artist, Cabinet, Placement, Shelf
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.web.app import create_app


def _config(tmp_path, text):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / CONFIG_FILE).write_text(text, encoding="utf-8")


def test_numbers_written_as_text_are_read_as_numbers(tmp_path):
    _config(
        tmp_path,
        'base_width_cm: "0.6"\nsurcharge_180_gram_cm: "0,15"\ntable_records: "40"\n'
        'shelf_room_percent: 12.0\ncount_bonus_discs_as_vinyl: "no"\n',
    )

    settings = load_settings(tmp_path)

    assert settings.base_width_cm == 0.6 and isinstance(settings.base_width_cm, float)
    assert settings.surcharge_180_gram_cm == 0.15
    assert settings.table_records == 40 and isinstance(settings.table_records, int)
    assert settings.shelf_room_percent == 12 and isinstance(settings.shelf_room_percent, int)
    assert settings.count_bonus_discs_as_vinyl is False
    assert settings.width_constants.base_per_disc == 0.6


def test_what_cannot_be_read_keeps_the_default_and_says_so(tmp_path, caplog):
    _config(tmp_path, 'base_width_cm: "wide"\ntable_records: 12.5\ndiscogs_token: "abc"\n')

    with caplog.at_level(logging.WARNING):
        settings = load_settings(tmp_path)

    defaults = Settings()
    assert settings.base_width_cm == defaults.base_width_cm
    assert settings.table_records == defaults.table_records
    # Text stays text.
    assert settings.discogs_token == "abc"
    assert "base_width_cm" in caplog.text and "table_records" in caplog.text


def test_layout_shows_with_a_width_written_as_text(tmp_path):
    data = tmp_path / "data"
    store = JsonStore(data)
    store.save(Cabinet, [Cabinet(1, "Kast", position=0)])
    store.save(Shelf, [Shelf(1, 1, "a", width_cm=10.0, position=0)])
    store.save(Artist, [Artist(1, "Cream")])
    # No format, so the album's width comes from the base width in config.yaml.
    store.save(Album, [Album(1, 1, "Fresh Cream")])
    store.save(Placement, [Placement(1, 1, 0)])
    _config(data, 'base_width_cm: "0.5"\n')
    client = create_app(data).test_client()

    assert client.get("/layout/").status_code == 200
    assert client.get("/layout/glance").status_code == 200
