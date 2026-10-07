"""Per-request access to the store."""

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
