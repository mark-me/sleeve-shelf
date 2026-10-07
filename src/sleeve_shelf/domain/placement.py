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
class ShowcaseFeature:
    """An artist or album featured on a showcase shelf.

    Points at the unit's existing Placement, so it consumes no shelf width.
    """

    shelf_id: int
    unit_type: UnitType
    unit_id: int

    def __post_init__(self) -> None:
        if self.unit_type is UnitType.ERA_BAND:
            raise ValueError("A showcase features an artist or an album, not an era band")
