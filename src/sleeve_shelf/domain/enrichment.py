"""Discogs enrichment cache records, and proposed links between albums and releases."""

from dataclasses import dataclass
from datetime import datetime

from sleeve_shelf.domain.catalog import FormatTokens


@dataclass(frozen=True, slots=True)
class ReleaseEnrichment:
    """Cached result of a Discogs release lookup.

    The release's own year stands in as original year when it has no master.
    """

    release_id: int
    styles: tuple[str, ...]
    master_id: int | None
    fetched_at: datetime
    year: int | None = None


@dataclass(frozen=True, slots=True)
class MasterEnrichment:
    """Cached result of a Discogs master lookup."""

    master_id: int
    original_release_year: int | None
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class MatchProposal:
    """An uncertain link between a loaded album and a Discogs release, awaiting confirmation."""

    album_id: int
    release_id: int
    artist: str
    title: str
    score: float
    format_tokens: FormatTokens | None = None
