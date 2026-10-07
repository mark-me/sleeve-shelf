"""Tests for the JSON file store."""

import json

from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    Cabinet,
    Cluster,
    EraBand,
    EraBandSource,
    FormatTokens,
    Placement,
    PlacementSource,
    Shelf,
    ShelfLayer,
    ShelfType,
    UnitType,
)
from sleeve_shelf.persistence import JsonStore


def test_every_entity_round_trips(tmp_path):
    store = JsonStore(tmp_path)
    items = {
        Cabinet: [Cabinet(1, "Kast"), Cabinet(2, "Koffer", "Zolder")],
        Shelf: [
            Shelf(1, 1, "a"),
            Shelf(2, 1, "b", 80.5, ShelfType.TOP_LOADER, ShelfLayer.TOP, 1, True),
        ],
        Cluster: [Cluster(1, "Jazz: Cool / West Coast")],
        Artist: [Artist(1, 'Bonnie "Prince" Billy'), Artist(2, "Tom Waits", 82294, 3)],
        ArtistClusterAssignment: [
            ArtistClusterAssignment(1, 1, confirmed=True),
            ArtistClusterAssignment(2, None),
        ],
        EraBand: [EraBand(1, 1, "1990s", 0, EraBandSource.INITIAL_LOAD)],
        Album: [
            Album(1, 1, "Nénette Et Boni"),
            Album(
                2,
                2,
                "Closing Time",
                release_id=123,
                format_tokens=FormatTokens(2, True, True, False, ("2xLP", "Gat", "180")),
                computed_width_cm=1.5,
                master_id=456,
                original_release_year=1973,
                manual_width_cm=1.6,
                width_confirmed=False,
                style_ids=[4, 5],
                era_band_id=1,
            ),
        ],
        Placement: [Placement(UnitType.ALBUM, 2, 1, 0, PlacementSource.INITIAL_LOAD)],
    }

    for entity, values in items.items():
        store.save(entity, values)

    reopened = JsonStore(tmp_path)
    for entity, values in items.items():
        assert reopened.load(entity) == values


def test_files_are_plain_json_arrays(tmp_path):
    JsonStore(tmp_path).save(Cluster, [Cluster(1, "Jazz"), Cluster(2, "Rock")])

    content = json.loads((tmp_path / "clusters.json").read_text(encoding="utf-8"))

    assert content == [{"id": 1, "name": "Jazz"}, {"id": 2, "name": "Rock"}]


def test_save_replaces_previous_content(tmp_path):
    store = JsonStore(tmp_path)
    store.save(Cluster, [Cluster(1, "Jazz"), Cluster(2, "Rock")])

    store.save(Cluster, [Cluster(7, "Blues")])
    assert store.load(Cluster) == [Cluster(7, "Blues")]

    store.save(Cluster, [])
    assert store.load(Cluster) == []


def test_missing_file_loads_as_empty(tmp_path):
    assert JsonStore(tmp_path / "nowhere").load(Album) == []
