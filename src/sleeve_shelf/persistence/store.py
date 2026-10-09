"""JSON file store: one file per entity, read and written through DuckDB."""

import json
import os
import shutil
import time
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
)


SNAPSHOT_DIR = "placements"
SWAP_ATTEMPTS = 6


@dataclass(frozen=True, slots=True)
class _Table:
    """How one entity maps to its JSON file: columns with their DuckDB types."""

    filename: str
    columns: dict[str, str]
    decoders: dict[str, Callable[[Any], Any]] = field(default_factory=dict)
    # Columns that had another name in files written earlier: new name -> old name.
    # Such a file is still read; it gets the new names when it is next saved.
    renamed: dict[str, str] = field(default_factory=dict)


def _format_tokens(value: dict) -> FormatTokens:
    return FormatTokens(**{**value, "qualifiers": tuple(value["qualifiers"])})


_FORMAT_TOKENS_TYPE = (
    "STRUCT(disc_count INTEGER, is_180_gram BOOLEAN, is_gatefold BOOLEAN,"
    " is_compound BOOLEAN, qualifiers VARCHAR[])"
)

_PLACEMENT_COLUMNS = {
    "album_id": "INTEGER",
    "shelf_id": "INTEGER",
    "position": "INTEGER",
    "source": "VARCHAR",
}
# Until placements were per album only, the album was named by a unit id.
_PLACEMENT_RENAMED = {"album_id": "unit_id"}

@dataclass(slots=True)
class _IdMark:
    """The highest id ever handed out for one kind of entity, so that none is used twice."""

    name: str
    last_id: int


_TABLES: dict[type, _Table] = {
    _IdMark: _Table("id_marks.json", {"name": "VARCHAR", "last_id": "INTEGER"}),
    Cabinet: _Table(
        "cabinets.json",
        {
            "id": "INTEGER",
            "name": "VARCHAR",
            "location": "VARCHAR",
            "position": "INTEGER",
            "outside_sorting": "BOOLEAN",
        },
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
            "cover_image_url": "VARCHAR",
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
        {"source": PlacementSource},
        _PLACEMENT_RENAMED,
    ),
    ProposedPlacement: _Table(
        "placement_proposal.json",
        _PLACEMENT_COLUMNS,
        {"source": PlacementSource},
        _PLACEMENT_RENAMED,
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


def _swap_in(temporary: Path, target: Path) -> None:
    """Put a freshly written file in the place of the old one.

    On Windows the swap is refused while something else — a virus scanner,
    typically — has the file open for a moment, so it is tried a few times.
    """
    for attempt in range(SWAP_ATTEMPTS):
        try:
            os.replace(temporary, target)
            return
        except PermissionError:
            if attempt == SWAP_ATTEMPTS - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


class JsonStore:
    """Reads and writes each entity's JSON file in a data directory."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self._connection = duckdb.connect()
        self._id_marks: dict[str, int] | None = None

    def save[T](self, entity: type[T], items: Iterable[T]) -> None:
        """Overwrite the entity's file with exactly these items."""
        table = _TABLES[entity]
        rows = [{name: _encode(getattr(item, name)) for name in table.columns} for item in items]
        if "id" in table.columns:
            # Before anything is staged: recording the mark is a save of its own.
            self._remember_ids(entity, table, max((row["id"] for row in rows), default=0))
        columns = ", ".join(f'"{name}" {kind}' for name, kind in table.columns.items())
        self._connection.execute(f"CREATE OR REPLACE TEMP TABLE staging ({columns})")
        # Hand all rows to DuckDB as one JSON parameter: binding each value
        # separately costs seconds for a full collection.
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
        _swap_in(temporary, target)

    def next_id(self, entity: type, items: Iterable) -> int:
        """An id for a new item, given the items there are now: one that was never used before.

        An id is never handed out twice, not even after the item that had it is
        removed — a saved version, a location rule or a link may still name it,
        and would otherwise end up pointing at something else.
        """
        marked = self._marks().get(_TABLES[entity].filename, 0)
        return max(marked, max((item.id for item in items), default=0)) + 1

    def _marks(self) -> dict[str, int]:
        if self._id_marks is None:
            self._id_marks = {mark.name: mark.last_id for mark in self.load(_IdMark)}
        return self._id_marks

    def _remember_ids(self, entity: type, table: _Table, highest: int) -> None:
        """Keep the highest id of an entity on record, before its file is overwritten."""
        # Another store may have written since this one read the marks.
        self._id_marks = None
        marks = self._marks()
        known = marks.get(table.filename)
        if known is None and self.exists(entity):
            # No mark yet: what the file holds until now counts too, as an item may be leaving it.
            known = self.query(f'SELECT max("id") FROM {self.relation(entity)}')[0][0]
        last = max(known or 0, highest)
        if last != marks.get(table.filename):
            marks[table.filename] = last
            self.save(_IdMark, [_IdMark(name, last_id) for name, last_id in sorted(marks.items())])

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
        path = self.data_dir / table.filename
        if not path.exists():
            # Nothing of this kind was saved yet: an empty table with the same columns,
            # so a query that joins it finds no rows instead of failing.
            columns = ", ".join(
                f'CAST(NULL AS {kind}) AS "{name}"' for name, kind in table.columns.items()
            )
            return f"(SELECT {columns} WHERE false)"
        return self._read(table, path)

    @staticmethod
    def _read(table: _Table, path: Path) -> str:
        kinds = dict(table.columns)
        kinds.update({old: table.columns[new] for new, old in table.renamed.items()})
        columns = ", ".join(f"{_sql_string(name)}: {_sql_string(kind)}" for name, kind in kinds.items())
        file = f"read_json({_sql_string(path.as_posix())}, format = 'array', columns = {{{columns}}})"
        if not table.renamed:
            return file
        selected = ", ".join(
            f'coalesce("{name}", "{table.renamed[name]}") AS "{name}"' if name in table.renamed
            else f'"{name}"'
            for name in table.columns
        )
        return f"(SELECT {selected} FROM {file})"

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
        if not (current.exists() and saved.exists()):
            return False
        # Compared by content, not by bytes: an older version may still carry the old column names.
        return current.read_bytes() == saved.read_bytes() or (
            self.load(Placement) == self.load_snapshot(name)
        )

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
