"""Finding an item among others by its id."""

from collections.abc import Iterable
from typing import Protocol


class HasId(Protocol):
    """Anything with an id."""

    @property
    def id(self) -> int:
        """The item's id."""
        ...


def find_by_id[T: HasId](items: Iterable[T], item_id: int | None) -> T | None:
    """The item with this id.

    Args:
        items: The items to look through.
        item_id: The id; None finds nothing.

    Returns:
        The item, or None when there is none or no id is given.
    """
    if item_id is None:
        return None
    return next((item for item in items if item.id == item_id), None)
