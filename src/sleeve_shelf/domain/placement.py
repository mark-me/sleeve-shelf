"""Placement entities: where an album physically stands."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class PlacementSource(StrEnum):
    """Where a placement comes from: the sorting, a move by hand, or the initial load."""

    ALGORITHM = "algorithm"
    MANUAL = "manual"
    INITIAL_LOAD = "initial_load"


@dataclass(slots=True)
class Placement:
    """The one canonical location of an album; consumes shelf width.

    Attributes:
        album_id: The album.
        shelf_id: The shelf it stands on.
        position: Its place on the shelf.
        source: Where this placement comes from.
    """

    album_id: int
    shelf_id: int
    position: int
    source: PlacementSource = PlacementSource.ALGORITHM


@dataclass(slots=True)
class ProposedPlacement(Placement):
    """A placement in a sorting proposal, kept next to the current layout until accepted."""




@dataclass(slots=True)
class TargetPlacement(Placement):
    """Where a running reorganisation takes an album: the layout it carries out, step by step."""


@dataclass(slots=True)
class Reorganisation:
    """A proposal being carried out on the real shelves, a table full at a time.

    Only one runs at a time. Its steps are not kept: they are worked out each time from the
    shelves as they stand, so a change by hand meanwhile is taken into account.

    Attributes:
        started_at: When it started.
        table_records: How many records may be out of the cabinets at once.
        to_move: How many albums had to move when it started.
        moved: How many albums have reached their new place, or were left out, since.
        rounds_done: How many rounds were finished.
        taken_in_round: How many albums were taken out in the round at hand, so the plan worked
            out anew goes on with that round rather than starting a new one.
        on_table: The albums taken out and not yet put on a shelf.
        set_aside: The albums put somewhere else for now, as the table was not enough.
        left_out: The albums the new layout has no place for: they end up without one.
    """

    started_at: datetime
    table_records: int
    to_move: int
    moved: int = 0
    rounds_done: int = 0
    taken_in_round: int = 0
    on_table: list[int] = field(default_factory=list)
    set_aside: list[int] = field(default_factory=list)
    left_out: list[int] = field(default_factory=list)
