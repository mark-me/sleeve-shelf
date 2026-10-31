"""Per-request access to the store, and what the screens show of it alike."""

from flask import current_app, g

from sleeve_shelf.domain import Album
from sleeve_shelf.persistence import JsonStore


def get_store() -> JsonStore:
    """The store for the configured data directory, created once per request.

    Returns:
        The store.
    """
    if "store" not in g:
        g.store = JsonStore(current_app.config["DATA_DIR"])
    return g.store


def has_collection() -> bool:
    """Whether a collection has been loaded yet.

    Returns:
        True when there is one.
    """
    return get_store().exists(Album)


def shelf_fill(fill: dict[int, tuple[int, float]], shelf_id: int, digits: int | None = None) -> dict:
    """How full a shelf is, as the pages and the Layout's answers give it: albums and cm.

    Args:
        fill: The fill of all shelves, as BrowseQueries.shelf_fill gives it.
        shelf_id: The shelf.
        digits: Rounds the width to this many decimals.

    Returns:
        The albums and the width by name.
    """
    albums, filled_cm = fill.get(shelf_id, (0, 0.0))
    return {"albums": albums, "filled_cm": filled_cm if digits is None else round(filled_cm, digits)}


def parse_number(text: str) -> float | None:
    """A number as typed in a form, a decimal comma accepted.

    Args:
        text: What was typed.

    Returns:
        The number, or None when it isn't one.
    """
    try:
        return float(text.strip().replace(",", "."))
    except ValueError:
        return None
