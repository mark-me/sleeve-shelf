"""Finding an item among others by its id."""

from collections.abc import Iterable
from typing import Protocol


class HasId(Protocol):
    @property
    def id(self) -> int: ...


def find_by_id[T: HasId](items: Iterable[T], item_id: int | None) -> T | None:
    """The item with this id; None when there is none, or when no id is given."""
    if item_id is None:
        return None
    return next((item for item in items if item.id == item_id), None)
