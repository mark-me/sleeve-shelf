"""Persistence layer: stores domain objects as JSON files, read and written via DuckDB."""

from sleeve_shelf.persistence.browse import AlbumRow, BrowseQueries, ShelfSummary
from sleeve_shelf.persistence.store import JsonStore

__all__ = ["AlbumRow", "BrowseQueries", "JsonStore", "ShelfSummary"]
