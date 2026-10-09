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
    # Place in the order the cabinets are walked; see in_order().
    position: int | None = None
    # A sorting proposal leaves this cabinet as it is: nothing is taken from it or added to it.
    outside_sorting: bool = False


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
    # Place among the shelves of its cabinet; see in_order().
    position: int | None = None

    def __post_init__(self) -> None:
        if self.is_showcase and self.type is not ShelfType.TOP_LOADER:
            raise ValueError("Only a top-loader shelf can be a showcase")


def in_order[T: (Cabinet, Shelf)](items: list[T]) -> list[T]:
    """Cabinets, or the shelves of one cabinet, in the order they are walked.

    That is the order set by hand; items never moved keep the order they were
    added in.
    """
    return sorted(
        items, key=lambda item: (item.position if item.position is not None else item.id, item.id)
    )


def renumber[T: (Cabinet, Shelf)](items: list[T]) -> None:
    """Fix the given order as each item's position."""
    for position, item in enumerate(items):
        item.position = position


def settle_order(cabinets: list[Cabinet], shelves: list[Shelf]) -> None:
    """Give every cabinet, and every shelf within its cabinet, an explicit position."""
    renumber(in_order(cabinets))
    for cabinet in cabinets:
        renumber(in_order([shelf for shelf in shelves if shelf.cabinet_id == cabinet.id]))


def move[T: (Cabinet, Shelf)](items: list[T], item_id: int, step: int) -> None:
    """Move one item a step up (-1) or down (+1) among the given items."""
    ordered = in_order(items)
    index = next(i for i, item in enumerate(ordered) if item.id == item_id)
    target = index + step
    if 0 <= target < len(ordered):
        ordered[index], ordered[target] = ordered[target], ordered[index]
    renumber(ordered)


@dataclass(slots=True)
class LocationRule:
    """A manually created exception that pins a target to a mandatory cabinet."""

    id: int
    target_type: LocationRuleTarget
    target_id: int
    cabinet_id: int
    note: str = ""
