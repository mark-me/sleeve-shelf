"""JSON file store: one file per entity, read and written through DuckDB."""

import json
import os
import shutil
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import duckdb

from sleeve_shelf.domain import (
    Album,
    AliasGroup,
    Artist,
    ArtistClusterAssignment,
    Cabinet,
    Cluster,
    EraBand,
    EraBandSource,
    FamilyDismissal,
    FormatTokens,
    LocationRule,
    LocationRuleTarget,
    MasterEnrichment,
    MatchProposal,
    Placement,
    PlacementSource,
    ProposedPlacement,
    ReleaseEnrichment,
    Shelf,
    ShelfLayer,
    ShelfType,
    Style,
    UnitType,
)


SNAPSHOT_DIR = "placements"


@dataclass(frozen=True, slots=True)
class _Table:
    """How one entity maps to its JSON file: columns with their DuckDB types."""

    filename: str
    columns: dict[str, str]
    decoders: dict[str, Callable[[Any], Any]] = field(default_factory=dict)


def _format_tokens(value: dict) -> FormatTokens:
    return FormatTokens(**{**value, "qualifiers": tuple(value["qualifiers"])})


_FORMAT_TOKENS_TYPE = (
    "STRUCT(disc_count INTEGER, is_180_gram BOOLEAN, is_gatefold BOOLEAN,"
    " is_compound BOOLEAN, qualifiers VARCHAR[])"
)

_PLACEMENT_COLUMNS = {
    "unit_type": "VARCHAR",
    "unit_id": "INTEGER",
    "shelf_id": "INTEGER",
    "position": "INTEGER",
    "source": "VARCHAR",
}

_TABLES: dict[type, _Table] = {
    Cabinet: _Table(
        "cabinets.json",
        {"id": "INTEGER", "name": "VARCHAR", "location": "VARCHAR", "position": "INTEGER"},
    ),
    Shelf: _Table(
        "shelves.json",
        {
            "id": "INTEGER",
            "cabinet_id": "INTEGER",
            "name": "VARCHAR",
            "width_cm": "DOUBLE",
            "type": "VARCHAR",
            "layer": "VARCHAR",
            "reachability_score": "INTEGER",
            "is_showcase": "BOOLEAN",
            "position": "INTEGER",
        },
        {"type": ShelfType, "layer": ShelfLayer},
    ),
    Cluster: _Table(
        "clusters.json", {"id": "INTEGER", "name": "VARCHAR", "position": "INTEGER"}
    ),
    AliasGroup: _Table("alias_groups.json", {"id": "INTEGER", "label": "VARCHAR"}),
    LocationRule: _Table(
        "location_rules.json",
        {
            "id": "INTEGER",
            "target_type": "VARCHAR",
            "target_id": "INTEGER",
            "cabinet_id": "INTEGER",
            "note": "VARCHAR",
        },
        {"target_type": LocationRuleTarget},
    ),
    FamilyDismissal: _Table("family_dismissals.json", {"anchor_artist_id": "INTEGER"}),
    Artist: _Table(
        "artists.json",
        {
            "id": "INTEGER",
            "name": "VARCHAR",
            "discogs_artist_id": "INTEGER",
            "alias_group_id": "INTEGER",
            "start_year": "INTEGER",
        },
    ),
    ArtistClusterAssignment: _Table(
        "cluster_assignments.json",
        {"artist_id": "INTEGER", "cluster_id": "INTEGER", "confirmed": "BOOLEAN"},
    ),
    EraBand: _Table(
        "era_bands.json",
        {
            "id": "INTEGER",
            "artist_id": "INTEGER",
            "label": "VARCHAR",
            "position": "INTEGER",
            "source": "VARCHAR",
        },
        {"source": EraBandSource},
    ),
    Album: _Table(
        "albums.json",
        {
            "id": "INTEGER",
            "artist_id": "INTEGER",
            "title": "VARCHAR",
            "release_id": "INTEGER",
            "format_tokens": _FORMAT_TOKENS_TYPE,
            "computed_width_cm": "DOUBLE",
            "master_id": "INTEGER",
            "original_release_year": "INTEGER",
            "manual_width_cm": "DOUBLE",
            "width_confirmed": "BOOLEAN",
            "style_ids": "INTEGER[]",
            "era_band_id": "INTEGER",
            "cover_url": "VARCHAR",
            "original_year_confirmed": "BOOLEAN",
            "left_discogs": "BOOLEAN",
        },
        {"format_tokens": _format_tokens},
    ),
    Style: _Table(
        "styles.json", {"id": "INTEGER", "name": "VARCHAR", "cluster_id": "INTEGER"}
    ),
    ReleaseEnrichment: _Table(
        "discogs_releases.json",
        {
            "release_id": "INTEGER",
            "styles": "VARCHAR[]",
            "master_id": "INTEGER",
            "fetched_at": "TIMESTAMP",
            "year": "INTEGER",
        },
        {"styles": tuple},
    ),
    MasterEnrichment: _Table(
        "discogs_masters.json",
        {"master_id": "INTEGER", "original_release_year": "INTEGER", "fetched_at": "TIMESTAMP"},
    ),
    MatchProposal: _Table(
        "match_proposals.json",
        {
            "album_id": "INTEGER",
            "release_id": "INTEGER",
            "artist": "VARCHAR",
            "title": "VARCHAR",
            "score": "DOUBLE",
            "format_tokens": _FORMAT_TOKENS_TYPE,
        },
        {"format_tokens": _format_tokens},
    ),
    Placement: _Table(
        "placement_current.json",
        _PLACEMENT_COLUMNS,
        {"unit_type": UnitType, "source": PlacementSource},
    ),
    ProposedPlacement: _Table(
        "placement_proposal.json",
        _PLACEMENT_COLUMNS,
        {"unit_type": UnitType, "source": PlacementSource},
    ),
}


def _encode(value: Any) -> Any:
    """Turn a domain value into something DuckDB can bind as a parameter."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if is_dataclass(value):
        return {key: _encode(item) for key, item in asdict(value).items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    return value


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class JsonStore:
    """Reads and writes each entity's JSON file in a data directory."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self._connection = duckdb.connect()

    def save[T](self, entity: type[T], items: Iterable[T]) -> None:
        """Overwrite the entity's file with exactly these items."""
        table = _TABLES[entity]
        columns = ", ".join(f'"{name}" {kind}' for name, kind in table.columns.items())
        self._connection.execute(f"CREATE OR REPLACE TEMP TABLE staging ({columns})")
        # Hand all rows to DuckDB as one JSON parameter: binding each value
        # separately costs seconds for a full collection.
        rows = [{name: _encode(getattr(item, name)) for name in table.columns} for item in items]
        self._connection.execute(
            "INSERT INTO staging SELECT row.* FROM (SELECT unnest(from_json(?, ?)) AS row)",
            [json.dumps(rows), json.dumps([table.columns])],
        )

        self.data_dir.mkdir(parents=True, exist_ok=True)
        target = self.data_dir / table.filename
        # Write next to the target and swap, so a crash never leaves a half-written file.
        temporary = target.with_suffix(".json.tmp")
        self._connection.execute(
            f"COPY staging TO {_sql_string(temporary.as_posix())} (FORMAT JSON, ARRAY true)"
        )
        os.replace(temporary, target)

    def load[T](self, entity: type[T]) -> list[T]:
        """Read all items of the entity; a file that doesn't exist yet yields none."""
        table = _TABLES[entity]
        if not self.exists(entity):
            return []
        rows = self._connection.execute(f"SELECT * FROM {self.relation(entity)}").fetchall()
        return [self._decode(entity, table, row) for row in rows]

    def exists(self, entity: type) -> bool:
        """Whether the entity's file has been written."""
        return (self.data_dir / _TABLES[entity].filename).exists()

    def remove(self, entity: type) -> None:
        """Delete the entity's file, if it was written."""
        (self.data_dir / _TABLES[entity].filename).unlink(missing_ok=True)

    def relation(self, entity: type) -> str:
        """The SQL table expression that reads the entity's file, for use in queries."""
        table = _TABLES[entity]
        return self._read(table, self.data_dir / table.filename)

    @staticmethod
    def _read(table: _Table, path: Path) -> str:
        columns = ", ".join(
            f"{_sql_string(name)}: {_sql_string(kind)}" for name, kind in table.columns.items()
        )
        return f"read_json({_sql_string(path.as_posix())}, format = 'array', columns = {{{columns}}})"

    def query(self, sql: str, parameters: list | None = None) -> list[tuple]:
        """Run a read query; refer to entities through relation()."""
        return self._connection.execute(sql, parameters or []).fetchall()

    def save_snapshot(self, name: str) -> Path:
        """Keep a copy of the current placement as a saved layout version."""
        snapshots = self.data_dir / SNAPSHOT_DIR
        snapshots.mkdir(parents=True, exist_ok=True)
        target = snapshots / f"{name}.json"
        shutil.copyfile(self.data_dir / _TABLES[Placement].filename, target)
        return target

    def snapshots(self) -> list[str]:
        """The names of the saved layout versions, oldest first."""
        return sorted(path.stem for path in (self.data_dir / SNAPSHOT_DIR).glob("*.json"))

    def load_snapshot(self, name: str) -> list[Placement]:
        """The placements of a saved layout version."""
        table = _TABLES[Placement]
        path = self.data_dir / SNAPSHOT_DIR / f"{name}.json"
        rows = self._connection.execute(
            f"SELECT * FROM {self._read(table, path)}"
        ).fetchall()
        return [self._decode(Placement, table, row) for row in rows]

    def snapshot_is_current(self, name: str) -> bool:
        """Whether a saved version is exactly the current layout."""
        current = self.data_dir / _TABLES[Placement].filename
        saved = self.data_dir / SNAPSHOT_DIR / f"{name}.json"
        return current.exists() and saved.exists() and current.read_bytes() == saved.read_bytes()

    def clear_snapshots(self) -> None:
        """Remove all saved layout versions."""
        shutil.rmtree(self.data_dir / SNAPSHOT_DIR, ignore_errors=True)

    @staticmethod
    def _decode[T](entity: type[T], table: _Table, row: tuple) -> T:
        values = dict(zip(table.columns, row))
        for name, decoder in table.decoders.items():
            if values[name] is not None:
                values[name] = decoder(values[name])
        return entity(**values)
