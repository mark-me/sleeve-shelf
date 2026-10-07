"""Discogs enrichment cache records, keyed by release and master ID."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ReleaseEnrichment:
    """Cached result of a Discogs release lookup."""

    release_id: int
    styles: tuple[str, ...]
    master_id: int | None
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class MasterEnrichment:
    """Cached result of a Discogs master lookup."""

    master_id: int
    original_release_year: int | None
    fetched_at: datetime
