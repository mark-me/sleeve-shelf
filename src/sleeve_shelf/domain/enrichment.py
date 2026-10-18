"""Discogs enrichment cache records, and proposed links between albums and releases."""

from dataclasses import dataclass
from datetime import datetime

from sleeve_shelf.domain.catalog import FormatTokens


@dataclass(frozen=True, slots=True)
class Track:
    """A song on a release, as Discogs lists it."""

    # Where it is on the record: "A1", "B2", or just a number.
    position: str
    title: str
    duration: str | None = None


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
    # The songs on the release. None means a record from before tracklists were kept, which
    # is fetched again once for its tracklist alone.
    tracklist: tuple[Track, ...] | None = None


@dataclass(frozen=True, slots=True)
class MasterEnrichment:
    """Cached result of a Discogs master lookup."""

    master_id: int
    original_release_year: int | None
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class ArtistEnrichment:
    """Cached result of a Discogs artist lookup: the artist's picture, if Discogs has one."""

    discogs_artist_id: int
    # The picture in full, and the small one of 150 px.
    image_url: str | None
    thumb_url: str | None
    fetched_at: datetime
    # Who Discogs says the artist is made of, belongs to, or is also known as: artist ids.
    # None means a record from before these were kept, which is fetched again.
    member_ids: tuple[int, ...] | None = None
    group_ids: tuple[int, ...] | None = None
    alias_ids: tuple[int, ...] | None = None


@dataclass(frozen=True, slots=True)
class MatchProposal:
    """An uncertain link between a loaded album and a Discogs release, awaiting confirmation."""

    album_id: int
    release_id: int
    artist: str
    title: str
    score: float
    format_tokens: FormatTokens | None = None
    # The cover of that release, as a sync gave it, for the album to take with the release.
    cover_url: str | None = None
    cover_image_url: str | None = None


@dataclass(frozen=True, slots=True)
class AlbumListening:
    """Where an album can be listened to: its album at Deezer, and its release's videos.

    Kept so an album's page does not search Deezer or ask Discogs again each time; the
    previews themselves are fetched afresh, as their addresses expire.
    """

    album_id: int
    checked_at: datetime
    # The album at Deezer, as found by artist and title; None when none was found.
    deezer_album_id: int | None = None
    deezer_title: str | None = None
    deezer_artist: str | None = None
    deezer_cover: str | None = None
    # The user said the album found is another one: it is not offered again.
    turned_down: bool = False
    # The videos Discogs lists for the album's release; None until they were asked for.
    video_titles: tuple[str, ...] | None = None
    video_urls: tuple[str, ...] | None = None
