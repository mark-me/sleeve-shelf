"""Placement entities: where an album physically stands."""

from dataclasses import dataclass
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


