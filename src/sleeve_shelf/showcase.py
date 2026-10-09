"""Application services for the showcase: a sample of the well-represented artists on display.

A showcase shelf holds a few albums of an artist, facing front, while the rest
of that artist's albums stand on their ordinary shelf. An album stands in one
place only, so the showcase takes no room on the ordinary shelf and the other
way round.
"""

from dataclasses import dataclass, field

from sleeve_shelf.domain import AliasGroup, Artist, Placement, Shelf
from sleeve_shelf.persistence import AlbumRow, BrowseQueries, JsonStore
from sleeve_shelf.sorting.families import sort_name
from sleeve_shelf.versions import keep_restore_point


@dataclass(slots=True)
class Sample:
    """One artist — or family — on a showcase shelf, next to what stays on the ordinary shelves."""

    name: str
    shown: list[AlbumRow] = field(default_factory=list)
    shelved: list[AlbumRow] = field(default_factory=list)
    unplaced: int = 0

    @property
    def total(self) -> int:
        return len(self.shown) + len(self.shelved) + self.unplaced

    @property
    def share(self) -> float:
        return len(self.shown) / self.total if self.total else 0.0


def showcase_shelf_ids(store: JsonStore) -> set[int]:
    return {shelf.id for shelf in store.load(Shelf) if shelf.is_showcase}


def _unit_of(store: JsonStore) -> tuple[dict[int, object], dict[object, str]]:
    """Which unit each artist belongs to — its family, or itself — and what each unit is called."""
    labels = {group.id: group.label for group in store.load(AliasGroup)}
    unit_of: dict[int, object] = {}
    names: dict[object, str] = {}
    for artist in store.load(Artist):
        in_family = artist.alias_group_id in labels
        unit = ("family", artist.alias_group_id) if in_family else ("artist", artist.id)
        unit_of[artist.id] = unit
        names[unit] = labels[artist.alias_group_id] if in_family else artist.name
    return unit_of, names


def samples(store: JsonStore, shelf_id: int) -> list[Sample]:
    """The artists shown on one showcase shelf, each with its albums on display and elsewhere."""
    showcase_ids = showcase_shelf_ids(store)
    unit_of, names = _unit_of(store)
    result: dict[object, Sample] = {}
    rows = BrowseQueries(store).everything()
    for row in rows:
        if row.shelf_id == shelf_id:
            unit = unit_of[row.artist_id]
            result.setdefault(unit, Sample(names[unit])).shown.append(row)
    for row in rows:
        sample = result.get(unit_of[row.artist_id])
        # What stands on another showcase shelf is shown there, not counted as shelved here.
        if sample is None or not row.is_lp or row.shelf_id in showcase_ids:
            continue
        if row.shelf_id is None:
            sample.unplaced += 1
        else:
            sample.shelved.append(row)
    return sorted(result.values(), key=lambda sample: sort_name(sample.name))


def swap(store: JsonStore, shown_album_id: int, shelved_album_id: int) -> bool:
    """Exchange an album on a showcase shelf with one of the same artist on an ordinary shelf.

    Each takes the other's spot, so both shelves hold as many albums as before.
    Returns False, changing nothing, when the two can't be exchanged.
    """
    showcase_ids = showcase_shelf_ids(store)
    placements = store.load(Placement)
    by_album = {p.album_id: p for p in placements}
    shown, shelved = by_album.get(shown_album_id), by_album.get(shelved_album_id)
    if shown is None or shelved is None:
        return False
    if shown.shelf_id not in showcase_ids or shelved.shelf_id in showcase_ids:
        return False
    unit_of, _names = _unit_of(store)
    artist_of = {row.album_id: row.artist_id for row in BrowseQueries(store).everything()}
    if unit_of[artist_of[shown_album_id]] != unit_of[artist_of[shelved_album_id]]:
        return False
    keep_restore_point(store)
    shown.shelf_id, shelved.shelf_id = shelved.shelf_id, shown.shelf_id
    shown.position, shelved.position = shelved.position, shown.position
    store.save(Placement, placements)
    return True
