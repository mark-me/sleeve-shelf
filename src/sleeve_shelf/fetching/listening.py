"""Application services for listening to an album: Deezer's previews and Discogs' videos.

What was found is kept (`AlbumListening`), so an album's page asks Deezer and Discogs only
the first time; the previews themselves are fetched each time, as their addresses expire.
Nothing here is needed for anything else: without a connection the album's page simply
says listening is not available.
"""

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from sleeve_shelf.domain import Album, AlbumListening, Artist, find_by_id
from sleeve_shelf.ingestion.deezer import (
    DeezerAlbum,
    DeezerClient,
    DeezerError,
    DeezerTrack,
)
from sleeve_shelf.ingestion.discogs_api import (
    DiscogsClient,
    DiscogsError,
    is_web_address,
)
from sleeve_shelf.persistence import JsonStore

# An album Deezer did not have is looked for again after this long: catalogues grow.
LOOK_AGAIN_AFTER = timedelta(days=30)
# The time an album never looked for at Deezer counts as checked: long ago, so it is due.
NEVER = datetime(2000, 1, 1)

_YOUTUBE = re.compile(r"(?:youtube\.com/watch\?(?:.*&)?v=|youtu\.be/)([\w-]{11})")


@dataclass(frozen=True, slots=True)
class Video:
    title: str
    url: str

    @property
    def youtube_id(self) -> str | None:
        """The id to embed the video by, when it is on YouTube."""
        found = _YOUTUBE.search(self.url)
        return found.group(1) if found else None


@dataclass(frozen=True, slots=True)
class Listening:
    """What can be played of an album, for its page."""

    album: DeezerAlbum | None = None
    tracks: list[DeezerTrack] = field(default_factory=list)
    videos: list[Video] = field(default_factory=list)
    turned_down: bool = False
    # Deezer or Discogs could not be reached: there may be more than is shown.
    unreachable: bool = False


def listening(
    store: JsonStore, album_id: int, deezer: DeezerClient, discogs: DiscogsClient | None
) -> Listening | None:
    """What can be played of an album; None when there is no such album.

    Looks the album up at Deezer and its release's videos up at Discogs when that was not
    done yet, and keeps what it found.
    """
    album = find_by_id(store.load(Album), album_id)
    if album is None:
        return None
    artist = find_by_id(store.load(Artist), album.artist_id)
    kept = _kept(store, album_id)
    record = kept or AlbumListening(album_id, NEVER)
    unreachable = False

    if (
        record.deezer_album_id is None
        and not record.turned_down
        and _now() - record.checked_at >= LOOK_AGAIN_AFTER
    ):
        try:
            found = deezer.find_album(artist.name if artist else "", album.title)
            record = replace(
                record,
                checked_at=_now(),
                deezer_album_id=found.id if found else None,
                deezer_title=found.title if found else None,
                deezer_artist=found.artist if found else None,
                deezer_cover=found.cover if found else None,
            )
        except DeezerError:
            unreachable = True

    if record.video_urls is None and album.release_id is not None and discogs is not None:
        try:
            videos = discogs.videos(album.release_id)
            record = replace(
                record,
                video_titles=tuple(title for title, _ in videos),
                video_urls=tuple(url for _, url in videos),
            )
        except DiscogsError:
            unreachable = True

    if record != kept:
        _keep(store, record)

    tracks: list[DeezerTrack] = []
    deezer_album = None
    if record.deezer_album_id is not None and not record.turned_down:
        deezer_album = DeezerAlbum(
            record.deezer_album_id, record.deezer_title or "", record.deezer_artist or "", record.deezer_cover
        )
        try:
            tracks = deezer.tracks(record.deezer_album_id)
        except DeezerError:
            unreachable = True

    # Kept before addresses were checked, a video could still hold another kind of link.
    videos = [
        Video(title, url)
        for title, url in zip(record.video_titles or (), record.video_urls or ())
        if is_web_address(url)
    ]
    return Listening(deezer_album, tracks, videos, record.turned_down, unreachable)


def turn_down(store: JsonStore, album_id: int) -> None:
    """The album Deezer gave is another one: it is no longer offered for this album."""
    record = _kept(store, album_id) or AlbumListening(album_id, NEVER)
    _keep(store, replace(record, turned_down=True))


def _kept(store: JsonStore, album_id: int) -> AlbumListening | None:
    return next((r for r in store.load(AlbumListening) if r.album_id == album_id), None)


def _keep(store: JsonStore, record: AlbumListening) -> None:
    others = [r for r in store.load(AlbumListening) if r.album_id != record.album_id]
    store.save(AlbumListening, [*others, record])


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)
