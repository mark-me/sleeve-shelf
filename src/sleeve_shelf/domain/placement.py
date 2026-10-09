"""Placement entities: where an album physically stands."""

from dataclasses import dataclass
from enum import StrEnum


class PlacementSource(StrEnum):
    ALGORITHM = "algorithm"
    MANUAL = "manual"
    INITIAL_LOAD = "initial_load"


@dataclass(slots=True)
class Placement:
    """The one canonical location of an album; consumes shelf width."""

    album_id: int
    shelf_id: int
    position: int
    source: PlacementSource = PlacementSource.ALGORITHM


@dataclass(slots=True)
class ProposedPlacement(Placement):
    """A placement in a sorting proposal, kept next to the current layout until accepted."""


