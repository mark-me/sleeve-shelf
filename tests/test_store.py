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
        Placement: [Placement(2, 1, 0, PlacementSource.INITIAL_LOAD)],
    }

    for entity, values in items.items():
        store.save(entity, values)

    reopened = JsonStore(tmp_path)
    for entity, values in items.items():
        assert reopened.load(entity) == values


def test_files_are_plain_json_arrays(tmp_path):
    JsonStore(tmp_path).save(Cluster, [Cluster(1, "Jazz"), Cluster(2, "Rock")])

    content = json.loads((tmp_path / "clusters.json").read_text(encoding="utf-8"))

    assert content == [
        {"id": 1, "name": "Jazz", "position": None},
        {"id": 2, "name": "Rock", "position": None},
    ]


def test_save_replaces_previous_content(tmp_path):
    store = JsonStore(tmp_path)
    store.save(Cluster, [Cluster(1, "Jazz"), Cluster(2, "Rock")])

    store.save(Cluster, [Cluster(7, "Blues")])
    assert store.load(Cluster) == [Cluster(7, "Blues")]

    store.save(Cluster, [])
    assert store.load(Cluster) == []


def test_missing_file_loads_as_empty(tmp_path):
    assert JsonStore(tmp_path / "nowhere").load(Album) == []


def test_an_id_is_never_handed_out_twice(tmp_path):
    store = JsonStore(tmp_path)
    store.save(Cluster, [Cluster(1, "Jazz"), Cluster(2, "Rock"), Cluster(3, "Blues")])
    assert store.next_id(Cluster, store.load(Cluster)) == 4

    # The highest one goes; its id stays taken, also for a store opened later.
    store.save(Cluster, [Cluster(1, "Jazz"), Cluster(2, "Rock")])

    assert store.next_id(Cluster, store.load(Cluster)) == 4
    assert JsonStore(tmp_path).next_id(Cluster, [Cluster(1, "Jazz")]) == 4
    # Items made but not saved yet count as well.
    assert store.next_id(Cluster, [Cluster(1, "Jazz"), Cluster(9, "New")]) == 10
    assert store.load(Cluster) == [Cluster(1, "Jazz"), Cluster(2, "Rock")]


def test_ids_in_files_from_before_the_marks_existed_stay_taken(tmp_path):
    store = JsonStore(tmp_path)
    store.save(Cluster, [Cluster(1, "Jazz"), Cluster(5, "Rock")])
    (tmp_path / "id_marks.json").unlink()

    # The first save since removes the highest: what the file held counts.
    JsonStore(tmp_path).save(Cluster, [Cluster(1, "Jazz")])

    assert JsonStore(tmp_path).next_id(Cluster, [Cluster(1, "Jazz")]) == 6
    assert JsonStore(tmp_path).next_id(Album, []) == 1


def test_placements_written_before_they_were_per_album_only_are_still_read(tmp_path):
    store = JsonStore(tmp_path)
    old = '[{"unit_type":"album","unit_id":7,"shelf_id":2,"position":0,"source":"manual"}]'
    (tmp_path / "placement_current.json").write_text(old)
    (tmp_path / "placements").mkdir()
    (tmp_path / "placements" / "earlier.json").write_text(old)

    expected = [Placement(7, 2, 0, PlacementSource.MANUAL)]
    assert store.load(Placement) == expected
    assert store.load_snapshot("earlier") == expected

    # Saved again, the file carries the new name; the older version still counts as the same layout.
    store.save(Placement, expected)
    assert '"album_id":7' in (tmp_path / "placement_current.json").read_text().replace(" ", "")
    assert store.snapshot_is_current("earlier")
