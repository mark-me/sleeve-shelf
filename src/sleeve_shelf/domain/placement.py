"""Placement entities: where a unit physically lives, and what a showcase features."""

from dataclasses import dataclass
from enum import StrEnum


class UnitType(StrEnum):
    ARTIST = "artist"
    ERA_BAND = "era_band"
    ALBUM = "album"


class PlacementSource(StrEnum):
    ALGORITHM = "algorithm"
    MANUAL = "manual"
    INITIAL_LOAD = "initial_load"


@dataclass(slots=True)
class Placement:
    """The one canonical location of a unit; consumes shelf width.

    The most specific unit wins: an album's own placement, else its era
    band's, else its artist's.
    """

    unit_type: UnitType
    unit_id: int
    shelf_id: int
    position: int
    source: PlacementSource = PlacementSource.ALGORITHM


@dataclass(slots=True)
class ProposedPlacement(Placement):
    """A placement in a sorting proposal, kept next to the current layout until accepted."""


