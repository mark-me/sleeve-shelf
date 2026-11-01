"""Storage structure entities: cabinets, shelves, and location rules."""

from dataclasses import dataclass
from enum import StrEnum


class ShelfType(StrEnum):
    """The kind of shelf: a top-loader or a front-loader."""

    TOP_LOADER = "top_loader"
    FRONT_LOADER = "front_loader"


class ShelfLayer(StrEnum):
    """The row of a cabinet a shelf is in: the top or the bottom."""

    TOP = "top"
    BOTTOM = "bottom"


class LocationRuleTarget(StrEnum):
    """What a location rule binds to a cabinet."""

    ARTIST = "artist"
    ALIAS_GROUP = "alias_group"
    CLUSTER = "cluster"
    ALBUM = "album"


@dataclass(slots=True)
class Cabinet:
    """A record cabinet in a room.

    Attributes:
        id: The cabinet's id.
        name: The cabinet's name.
        location: The room it stands in, if given.
        position: Place in the order the cabinets are walked; see in_order().
        outside_sorting: A sorting proposal leaves this cabinet as it is: nothing is taken from it
            or added to it.
    """

    id: int
    name: str
    location: str | None = None
    position: int | None = None
    outside_sorting: bool = False


@dataclass(frozen=True, slots=True)
class RuleSuggestionDismissal:
    """A location rule the layout hinted at, which the user turned down for good.

    Attributes:
        target_type: What the rule would bind.
        target_id: The id of that.
        cabinet_id: The cabinet it would be bound to.
    """

    target_type: LocationRuleTarget
    target_id: int
    cabinet_id: int


@dataclass(slots=True)
class Shelf:
    """A shelf within a cabinet; its width determines how many records fit.

    Shelves seeded by the initial load only have a name; the physical attributes stay None until
    completed in the storage structure.

    Attributes:
        id: The shelf's id.
        cabinet_id: The cabinet it is in.
        name: The shelf's name.
        width_cm: Its width, if known.
        type: Top-loader or front-loader.
        layer: The row it is in: top or bottom.
        reachability_score: The reachability score: a whole number, from the workbook or entered by hand; it does
            not steer the sorting.
        is_showcase: Whether it holds a sample of an artist's albums; only a top-loader can.
        position: Place among the shelves of its cabinet; see in_order().
        width_measured: Whether the width was measured; otherwise it is an estimate, as from the
            workbook.

    Raises:
        ValueError: A showcase shelf that is not a top-loader.
    """

    id: int
    cabinet_id: int
    name: str
    width_cm: float | None = None
    type: ShelfType | None = None
    layer: ShelfLayer | None = None
    reachability_score: int | None = None
    is_showcase: bool = False
    position: int | None = None
    width_measured: bool = False

    def __post_init__(self) -> None:
        # A shelf saved before this was kept has no value: its width counts as an estimate.
        self.width_measured = bool(self.width_measured) and self.width_cm is not None
        if self.is_showcase and self.type is not ShelfType.TOP_LOADER:
            raise ValueError("Only a top-loader shelf can be a showcase")


def in_order[T: (Cabinet, Shelf)](items: list[T]) -> list[T]:
    """Cabinets, or the shelves of one cabinet, in the order they are walked.

    That is the order set by hand; items never moved keep the order they were added in.

    Args:
        items: The cabinets, or the shelves of one cabinet.

    Returns:
        The items in order.
    """
    return sorted(
        items, key=lambda item: (item.position if item.position is not None else item.id, item.id)
    )


def renumber[T: (Cabinet, Shelf)](items: list[T]) -> None:
    """Fix the given order as each item's position.

    Args:
        items: The cabinets or shelves, in the order to fix.
    """
    for position, item in enumerate(items):
        item.position = position


def settle_order(cabinets: list[Cabinet], shelves: list[Shelf]) -> None:
    """Give every cabinet, and every shelf within its cabinet, an explicit position.

    Args:
        cabinets: All cabinets.
        shelves: All shelves.
    """
    renumber(in_order(cabinets))
    for cabinet in cabinets:
        renumber(in_order([shelf for shelf in shelves if shelf.cabinet_id == cabinet.id]))


def move[T: (Cabinet, Shelf)](items: list[T], item_id: int, step: int) -> None:
    """Move one item a step up (-1) or down (+1) among the given items.

    Args:
        items: The items it stands among; positions are changed in place.
        item_id: The item to move.
        step: -1 for up, +1 for down.
    """
    ordered = in_order(items)
    index = next(i for i, item in enumerate(ordered) if item.id == item_id)
    target = index + step
    if 0 <= target < len(ordered):
        ordered[index], ordered[target] = ordered[target], ordered[index]
    renumber(ordered)


@dataclass(slots=True)
class LocationRule:
    """A manually created exception that pins a target to a mandatory cabinet.

    Attributes:
        id: The rule's id.
        target_type: What it binds.
        target_id: The id of that.
        cabinet_id: The cabinet it must stand in.
        note: Why, as the user or the app words it.
    """

    id: int
    target_type: LocationRuleTarget
    target_id: int
    cabinet_id: int
    note: str = ""
