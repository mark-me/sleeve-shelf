"""Storage structure entities: cabinets, shelves, and location rules."""

from dataclasses import dataclass
from enum import StrEnum


class ShelfType(StrEnum):
    TOP_LOADER = "top_loader"
    FRONT_LOADER = "front_loader"


class ShelfLayer(StrEnum):
    TOP = "top"
    BOTTOM = "bottom"


class LocationRuleTarget(StrEnum):
    ARTIST = "artist"
    ALIAS_GROUP = "alias_group"
    CLUSTER = "cluster"
    ALBUM = "album"


@dataclass(slots=True)
class Cabinet:
    """A record cabinet in a room."""

    id: int
    name: str
    location: str | None = None


@dataclass(slots=True)
class Shelf:
    """A shelf within a cabinet; its width determines how many records fit.

    Shelves seeded by the initial load only have a name; the physical
    attributes stay None until completed in the storage structure.
    """

    id: int
    cabinet_id: int
    name: str
    width_cm: float | None = None
    type: ShelfType | None = None
    layer: ShelfLayer | None = None
    reachability_score: int | None = None
    is_showcase: bool = False

    def __post_init__(self) -> None:
        if self.is_showcase and self.type is not ShelfType.TOP_LOADER:
            raise ValueError("Only a top-loader shelf can be a showcase")


@dataclass(slots=True)
class LocationRule:
    """A manually created exception that pins a target to a mandatory cabinet."""

    id: int
    target_type: LocationRuleTarget
    target_id: int
    cabinet_id: int
    note: str = ""
