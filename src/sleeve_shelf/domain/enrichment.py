"""Discogs enrichment cache records, and proposed links between albums and releases."""

import re
from dataclasses import dataclass
from datetime import datetime

from sleeve_shelf.domain.catalog import FormatTokens

# The credits that name who wrote a song: "Written-By", "Composed By", "Lyrics By", "Music By"…
WRITER_ROLE = re.compile(r"writ|compos|lyrics|music by|words by|songwriter", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Track:
    """A song on a release, as Discogs lists it.

    Attributes:
        position: Where it is on the record: "A1", "B2", or just a number.
        title: The title.
        duration: The length as Discogs gives it ("5:37"), if it does.
        writers: Who wrote it, as Discogs credits them: Discogs artist ids. Empty when Discogs names
            no one; None for a track fetched before writers were kept, fetched again once for them.
    """

    position: str
    title: str
    duration: str | None = None
    writers: tuple[int, ...] | None = None


@dataclass(frozen=True, slots=True)
class Credit:
    """Someone Discogs credits on a release, whatever for: all are kept, the screens choose.

    Attributes:
        discogs_artist_id: The person on Discogs.
        name: The name as credited.
        role: As Discogs words it: "Piano", "Producer", "Written-By, Arranged By".
        tracks: The tracks it is for, as Discogs words them ("A1 to A3"); empty for the whole
            release.
    """

    discogs_artist_id: int
    name: str
    role: str
    tracks: str = ""


@dataclass(frozen=True, slots=True)
class ReleaseLabel:
    """A record label on a release: of this pressing, so a reissue has the label of the reissue.

    Attributes:
        discogs_label_id: The label on Discogs.
        name: The name as Discogs gives it.
        catalogue_number: The catalogue number on this release.
    """

    discogs_label_id: int
    name: str
    catalogue_number: str = ""


@dataclass(frozen=True, slots=True)
class ReleaseEnrichment:
    """Cached result of a Discogs release lookup.

    The release's own year stands in as original year when it has no master.

    Attributes:
        release_id: The release.
        styles: Its styles as Discogs names them.
        master_id: Its master release, if it has one.
        fetched_at: When it was fetched.
        year: The year of the release.
        tracklist: The songs on the release. None means a record from before tracklists were kept,
            which is fetched again once for its tracklist alone.
        credits: Who is credited on the release. None means a record from before credits were kept,
            which is fetched again once for them.
        labels: The labels of the release. None means a record from before labels were kept, which
            is fetched again once for them.
    """

    release_id: int
    styles: tuple[str, ...]
    master_id: int | None
    fetched_at: datetime
    year: int | None = None
    tracklist: tuple[Track, ...] | None = None
    credits: tuple[Credit, ...] | None = None
    labels: tuple[ReleaseLabel, ...] | None = None


@dataclass(frozen=True, slots=True)
class MasterEnrichment:
    """Cached result of a Discogs master lookup.

    Attributes:
        master_id: The master release.
        original_release_year: The year it first came out.
        fetched_at: When it was fetched.
    """

    master_id: int
    original_release_year: int | None
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class ArtistEnrichment:
    """Cached result of a Discogs artist lookup: the artist's picture, if Discogs has one.

    Attributes:
        discogs_artist_id: The artist on Discogs.
        image_url: The picture in full.
        thumb_url: The small picture of 150 px.
        fetched_at: When it was fetched.
        member_ids: Who Discogs says the artist is made of: artist ids. None means a record from
            before these were kept, which is fetched again.
        group_ids: The bands Discogs says the artist belongs to; None as for member_ids.
        alias_ids: The other names Discogs lists for the artist; None as for member_ids.
    """

    discogs_artist_id: int
    image_url: str | None
    thumb_url: str | None
    fetched_at: datetime
    member_ids: tuple[int, ...] | None = None
    group_ids: tuple[int, ...] | None = None
    alias_ids: tuple[int, ...] | None = None


@dataclass(frozen=True, slots=True)
class MatchProposal:
    """An uncertain link between a loaded album and a Discogs release, awaiting confirmation.

    Attributes:
        album_id: The album.
        release_id: The release it may be.
        artist: The artist of the release.
        title: The title of the release.
        score: How alike the two are, from 0 to 1.
        format_tokens: The format of the release.
        cover_url: The cover of that release, as a sync gave it, for the album to take with the
            release.
        cover_image_url: The same cover as a large image.
    """

    album_id: int
    release_id: int
    artist: str
    title: str
    score: float
    format_tokens: FormatTokens | None = None
    cover_url: str | None = None
    cover_image_url: str | None = None


@dataclass(frozen=True, slots=True)
class AlbumListening:
    """Where an album can be listened to: its album at Deezer, and its release's videos.

    Kept so an album's page does not search Deezer or ask Discogs again each time; the previews
    themselves are fetched afresh, as their addresses expire.

    Attributes:
        album_id: The album.
        checked_at: When Deezer was asked.
        deezer_album_id: The album at Deezer, as found by artist and title; None when none was
            found.
        deezer_title: Its title at Deezer.
        deezer_artist: Its artist at Deezer.
        deezer_cover: Its cover at Deezer.
        turned_down: The user said the album found is another one: it is not offered again.
        video_titles: The titles of the videos Discogs lists for the album's release; None until
            they were asked for.
        video_urls: The addresses of those videos, in the same order.
    """

    album_id: int
    checked_at: datetime
    deezer_album_id: int | None = None
    deezer_title: str | None = None
    deezer_artist: str | None = None
    deezer_cover: str | None = None
    turned_down: bool = False
    video_titles: tuple[str, ...] | None = None
    video_urls: tuple[str, ...] | None = None


def credits_by_release(releases: list[ReleaseEnrichment]) -> dict[int, tuple[Credit, ...]]:
    """Who is credited on each release.

    Args:
        releases: The cached releases.

    Returns:
        The credits by release id; none for a release fetched before credits were kept.
    """
    return {release.release_id: release.credits or () for release in releases}
