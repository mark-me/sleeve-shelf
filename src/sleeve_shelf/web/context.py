"""Per-request access to the store, and what the screens show of it alike."""

from flask import current_app, g

from sleeve_shelf.domain import Album
from sleeve_shelf.persistence import JsonStore


def get_store() -> JsonStore:
    """The store for the configured data directory, created once per request."""
    if "store" not in g:
        g.store = JsonStore(current_app.config["DATA_DIR"])
    return g.store


def has_collection() -> bool:
    """Whether a collection has been loaded yet."""
    return get_store().exists(Album)


def shelf_fill(fill: dict[int, tuple[int, float]], shelf_id: int, digits: int | None = None) -> dict:
    """How full a shelf is, as the pages and the Layout's answers give it: albums and cm."""
    albums, filled_cm = fill.get(shelf_id, (0, 0.0))
    return {"albums": albums, "filled_cm": filled_cm if digits is None else round(filled_cm, digits)}
