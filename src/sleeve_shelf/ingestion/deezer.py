"""Client for the Deezer API: finding an album by artist and title, and its 30-second previews.

The API is free and needs no key. Previews are short MP3s; their addresses expire, so they
are fetched when they are to be played, never kept.
"""

import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher

API_ROOT = "https://api.deezer.com"
SEARCH_LIMIT = 10
# An album found counts only when both its title and its artist are this close to ours.
MIN_TITLE = 0.8
MIN_ARTIST = 0.7
# Words that make an album found another album than ours, unless ours has them too.
OTHER_ALBUM = ("live", "soundtrack", "karaoke", "tribute", "instrumental", "cover", "remix")


class DeezerError(Exception):
    """Deezer could not be reached, or answered with an error."""


@dataclass(frozen=True, slots=True)
class DeezerAlbum:
    id: int
    title: str
    artist: str
    cover: str | None

    @property
    def link(self) -> str:
        return f"https://www.deezer.com/album/{self.id}"


@dataclass(frozen=True, slots=True)
class DeezerTrack:
    title: str
    seconds: int
    # The 30-second preview; None when Deezer has none for this track.
    preview: str | None


class DeezerClient:
    def __init__(self, fetch: Callable[[str], bytes] | None = None) -> None:
        self._fetch = fetch or _fetch

    def find_album(self, artist: str, title: str) -> DeezerAlbum | None:
        """The album at Deezer that is ours, going by artist and title; None when none is."""
        first = first_artist(artist)
        queries = [f'artist:"{_plain(artist)}" album:"{_plain(title)}"']
        if first != artist:
            queries.append(f'artist:"{_plain(first)}" album:"{_plain(title)}"')
        queries.append(f"{_plain(first)} {_plain(title)}")
        # Narrow first, then wider: a search that finds only other albums tries the next.
        for query in queries:
            found = self._get("/search/album", q=query, limit=SEARCH_LIMIT).get("data") or []
            album = best_album(artist, title, found) if found else None
            if album is not None:
                return album
        return None

    def tracks(self, album_id: int) -> list[DeezerTrack]:
        data = self._get(f"/album/{album_id}/tracks", limit=100).get("data") or []
        return [
            DeezerTrack(track.get("title") or "", int(track.get("duration") or 0), track.get("preview") or None)
            for track in data
        ]

    def _get(self, path: str, **params) -> dict:
        url = API_ROOT + path + "?" + urllib.parse.urlencode(params)
        try:
            data = json.loads(self._fetch(url))
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise DeezerError(f"Deezer could not be reached: {error}") from error
        if isinstance(data, dict) and "error" in data:
            raise DeezerError(f"Deezer answered: {data['error']}")
        return data


def best_album(artist: str, title: str, candidates: list[dict]) -> DeezerAlbum | None:
    """The candidate that is our album: close in title and in artist, and not a live
    record, remix or soundtrack when ours is not. On a tie the shortest title, the plain
    edition, wins."""
    first = first_artist(artist)
    best, best_key = None, None
    for candidate in candidates:
        name = (candidate.get("artist") or {}).get("name") or ""
        title_close = _similar(title, candidate.get("title") or "")
        artist_close = max(_similar(artist, name), _similar(first, name))
        if title_close < MIN_TITLE or artist_close < MIN_ARTIST:
            continue
        # A live record, a remix or a soundtrack of the same name is another album: rather
        # nothing than that, unless ours is one too.
        if any(word in (candidate.get("title") or "").casefold() and word not in title.casefold() for word in OTHER_ALBUM):
            continue
        key = (round(title_close * 0.6 + artist_close * 0.4, 2), -len(candidate.get("title") or ""))
        if best_key is None or key > best_key:
            best, best_key = candidate, key
    if best is None:
        return None
    return DeezerAlbum(
        int(best["id"]),
        best.get("title") or "",
        (best.get("artist") or {}).get("name") or "",
        best.get("cover_medium") or best.get("cover") or None,
    )


def first_artist(artist: str) -> str:
    """The first of several artists credited together: "Duke Ellington, Charles Mingus"."""
    name = re.sub(r"\s*\(\d+\)$", "", artist)
    return re.split(r",|\s+(?:&|and|with|featuring|feat\.)\s+", name, maxsplit=1, flags=re.I)[0].strip()


def _plain(text: str) -> str:
    """A name as compared: no accents, no "(2)" or other bracketed additions, no signs."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
    text = re.sub(r"\s*\(\d+\)$", "", text.strip())
    text = re.sub(r"[\(\[].*?[\)\]]", "", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _similar(ours: str, theirs: str) -> float:
    return SequenceMatcher(None, _plain(ours), _plain(theirs)).ratio()


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read()
