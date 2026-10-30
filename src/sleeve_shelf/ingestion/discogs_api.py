"""Client for the Discogs API: the collection, and the release, master and artist lookups."""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime

from sleeve_shelf.domain import (
    ArtistEnrichment,
    MasterEnrichment,
    Credit,
    ReleaseEnrichment,
    Track,
)
from sleeve_shelf.ingestion.discogs_csv import CollectionItem
from sleeve_shelf.ingestion.formats import parse_format

API_ROOT = "https://api.discogs.com"
USER_AGENT = "SleeveShelf/0.1 +https://github.com/mark-me/sleeve-shelf"
# Authenticated requests are limited to 60 per minute.
SECONDS_BETWEEN_REQUESTS = 1.05
# Images come from Discogs' image servers, not from the API, and are paced more lightly.
SECONDS_BETWEEN_IMAGES = 0.25
RATE_LIMIT_PAUSE_SECONDS = 60
MAX_ATTEMPTS = 3
COLLECTION_PAGE_SIZE = 100
# The artist Discogs credits a compilation to; not an artist to look up.
VARIOUS_ARTISTS_ID = 194

# How the CSV export shortens the format descriptions the API spells out; the
# API-only ones say nothing about the record itself and are left out, as in the export.
_ABBREVIATIONS = {
    "Reissue": "RE",
    "Repress": "RP",
    "Remastered": "RM",
    "Compilation": "Comp",
    "Limited Edition": "Ltd",
    "Numbered": "Num",
    "Unofficial Release": "Unofficial",
    "Picture Disc": "Pic",
    "Misprint": "M/Print",
    "Special Edition": "S/Edition",
    "Deluxe Edition": "Dlx",
    "Single Sided": "S/Sided",
    "Etched": "Etch",
    "Record Store Day": "RSD",
}
_LEFT_OUT = {"Stereo", "45 RPM", "33 ⅓ RPM"}
# A 10" LP carries both descriptions; the export names it by its size, so that comes first.
_SIZES = ('7"', '10"', '12"', "LP")


class DiscogsError(Exception):
    """The API could not be reached or refused the request."""


class DiscogsClient:
    """Fetches releases and masters, pacing itself to the API's rate limit."""

    def __init__(
        self,
        token: str,
        fetch: Callable[[urllib.request.Request], bytes] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._token = token
        self._fetch = fetch or _fetch
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None

    def release(self, release_id: int) -> ReleaseEnrichment:
        """Styles, master, year and songs of a release; one that no longer exists yields none."""
        data = self._get(f"/releases/{release_id}") or {}
        return ReleaseEnrichment(
            release_id=release_id,
            styles=tuple(data.get("styles") or ()),
            master_id=data.get("master_id") or None,
            fetched_at=datetime.now().replace(microsecond=0),
            year=data.get("year") or None,
            tracklist=tracklist(data.get("tracklist"), data.get("extraartists")),
            credits=credits_of(data),
        )

    def videos(self, release_id: int) -> tuple[tuple[str, str], ...]:
        """The videos Discogs users linked to a release, as (title, address); mostly YouTube.

        Anyone can add a video to a release, so only web addresses are taken: a link such as
        `javascript:` would run a stranger's script within this app when clicked.
        """
        data = self._get(f"/releases/{release_id}") or {}
        return tuple(
            (video.get("title") or "", video["uri"])
            for video in data.get("videos") or ()
            if is_web_address(video.get("uri"))
        )

    def master(self, master_id: int) -> MasterEnrichment:
        """The original release year of a master."""
        data = self._get(f"/masters/{master_id}") or {}
        return MasterEnrichment(
            master_id=master_id,
            original_release_year=data.get("year") or None,
            fetched_at=datetime.now().replace(microsecond=0),
        )

    def artist(self, artist_id: int) -> ArtistEnrichment:
        """The picture of an artist; one without a picture, or that no longer exists, yields none."""
        data = self._get(f"/artists/{artist_id}") or {}
        images = data.get("images") or [{}]
        image = next((i for i in images if i.get("type") == "primary"), images[0])

        def ids(kind: str, active_only: bool = False) -> tuple[int, ...]:
            return tuple(
                int(entry["id"])
                for entry in data.get(kind) or []
                if entry.get("id") and not (active_only and entry.get("active") is False)
            )

        return ArtistEnrichment(
            discogs_artist_id=artist_id,
            image_url=image.get("uri") or None,
            thumb_url=image.get("uri150") or None,
            fetched_at=datetime.now().replace(microsecond=0),
            # Former members belong to the group's family too.
            member_ids=ids("members"),
            group_ids=ids("groups"),
            alias_ids=ids("aliases"),
        )

    def collection(self, progress: Callable[[int, int, int], None] | None = None) -> list[dict]:
        """Every release in the collection of the token's owner, as the API gives them.

        progress is told after each page: the pages fetched, of how many, and how many
        releases the collection holds — Discogs says so with the first page.
        """
        username = (self._get("/oauth/identity") or {}).get("username")
        if not username:
            raise DiscogsError("Discogs did not say whose token this is.")
        releases: list[dict] = []
        page = 1
        while True:
            data = self._get(
                f"/users/{username}/collection/folders/0/releases"
                f"?per_page={COLLECTION_PAGE_SIZE}&page={page}"
            )
            if data is None:
                raise DiscogsError("Discogs has no collection for this token.")
            releases.extend(data.get("releases") or ())
            pagination = data.get("pagination") or {}
            pages = pagination.get("pages", 1)
            if progress is not None:
                progress(page, pages, pagination.get("items", len(releases)))
            if page >= pages:
                return releases
            page += 1

    def image(self, url: str) -> bytes | None:
        """The bytes of a cover or picture; None when Discogs no longer has it."""
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._pace(SECONDS_BETWEEN_IMAGES)
            try:
                return self._fetch(request)
            except urllib.error.HTTPError as error:
                if error.code in (403, 404, 410):
                    return None
                if error.code == 429 and attempt < MAX_ATTEMPTS:
                    self._sleep(RATE_LIMIT_PAUSE_SECONDS)
                    continue
                raise DiscogsError(f"Discogs answered with HTTP {error.code}.") from error
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt < MAX_ATTEMPTS:
                    self._sleep(5)
                    continue
                raise DiscogsError(f"Discogs could not be reached: {error}") from error
        raise DiscogsError("Discogs kept limiting the requests.")

    def _get(self, path: str) -> dict | None:
        headers = {"User-Agent": USER_AGENT}
        # Without a token a few lookups still work, at a lower rate limit.
        if self._token:
            headers["Authorization"] = f"Discogs token={self._token}"
        request = urllib.request.Request(API_ROOT + path, headers=headers)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._pace()
            try:
                return json.loads(self._fetch(request))
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return None
                if error.code == 401:
                    raise DiscogsError("Discogs rejected the access token.") from error
                if error.code == 429 and attempt < MAX_ATTEMPTS:
                    self._sleep(RATE_LIMIT_PAUSE_SECONDS)
                    continue
                raise DiscogsError(f"Discogs answered with HTTP {error.code}.") from error
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt < MAX_ATTEMPTS:
                    self._sleep(5)
                    continue
                raise DiscogsError(f"Discogs could not be reached: {error}") from error
        raise DiscogsError("Discogs kept limiting the requests.")

    def _pace(self, seconds: float = SECONDS_BETWEEN_REQUESTS) -> None:
        now = self._clock()
        if self._last_request is not None:
            wait = seconds - (now - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._clock()


# The credits that name who wrote a song: "Written-By", "Composed By", "Lyrics By", "Music By"…
WRITER_ROLE = re.compile(r"writ|compos|lyrics|music by|words by|songwriter", re.IGNORECASE)


def _writers(credits: list[dict] | None) -> set[int]:
    return {c["id"] for c in credits or () if c.get("id") and WRITER_ROLE.search(c.get("role") or "")}


def tracklist(entries: list[dict] | None, credits: list[dict] | None = None) -> tuple[Track, ...]:
    """The songs of a Discogs tracklist, in order, each with who wrote it. A heading ("Side A")
    is no song; a medley or suite listed with its parts counts by its parts.

    The writers come from the track's own credits, its medley's, and the release's credits
    for the tracks they name ("A1 to A3, B2"), or for all of them when they name none.
    """
    songs: list[tuple[dict, set[int]]] = []
    for entry in entries or ():
        parts = entry.get("sub_tracks") or ()
        kind = entry.get("type_") or "track"
        for track in parts if parts else ([entry] if kind in ("track", "index") else []):
            if (track.get("title") or "").strip():
                own = _writers(track.get("extraartists"))
                songs.append((track, own | (_writers(entry.get("extraartists")) if parts else set())))
    positions = [track.get("position") or "" for track, _ in songs]
    for credit in credits or ():
        writers = _writers([credit])
        if not writers:
            continue
        for index in _credited(credit.get("tracks") or "", positions):
            songs[index][1].update(writers)
    return tuple(
        Track(track.get("position") or "", track["title"].strip(), track.get("duration") or None, tuple(sorted(writers)))
        for track, writers in songs
    )


def credits_of(data: dict) -> tuple[Credit, ...]:
    """Everyone a release credits, for the release or for a track, whatever the role. A name
    Discogs has no page for is left out: it cannot be compared with anyone."""

    def credit(entry: dict, tracks: str) -> Credit | None:
        if not entry.get("id") or not entry.get("role"):
            return None
        return Credit(entry["id"], (entry.get("name") or "").strip(), entry["role"].strip(), tracks)

    found = [credit(entry, (entry.get("tracks") or "").strip()) for entry in data.get("extraartists") or ()]
    for track in data.get("tracklist") or ():
        parts = track.get("sub_tracks") or ()
        where = ", ".join(part.get("position") or "" for part in parts) or track.get("position") or ""
        found += [credit(entry, where) for entry in track.get("extraartists") or ()]
        for part in parts:
            found += [credit(entry, part.get("position") or "") for entry in part.get("extraartists") or ()]
    return tuple(dict.fromkeys(item for item in found if item))


def _credited(tracks: str, positions: list[str]) -> list[int]:
    """The tracks a release credit is for: all of them when it names none, else those it names,
    one by one or as a range ("A1 to A3")."""
    if not tracks.strip():
        return list(range(len(positions)))
    found: list[int] = []
    for part in tracks.split(","):
        ends = [end.strip() for end in part.split(" to ")]
        if all(end in positions for end in ends):
            found += range(positions.index(ends[0]), positions.index(ends[-1]) + 1)
    return found


def is_web_address(address: str | None) -> bool:
    """Whether an address from outside is a plain web page: http or https, with a host."""
    if not address:
        return False
    parts = urllib.parse.urlsplit(address.strip())
    return parts.scheme.lower() in ("http", "https") and bool(parts.netloc)


def _fetch(request: urllib.request.Request) -> bytes:
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def collection_items(
    releases: list[dict], count_bonus_discs_as_vinyl: bool = True
) -> list[CollectionItem]:
    """Turn the releases of the collection API into the items the CSV export gives."""
    items = []
    for release in releases:
        information = release.get("basic_information") or {}
        parsed = parse_format(
            format_text(information.get("formats") or ()), count_bonus_discs_as_vinyl
        )
        items.append(
            CollectionItem(
                release_id=int(release["id"]),
                artist=_artist_name(information.get("artists") or ()),
                title=(information.get("title") or "").strip(),
                is_vinyl=parsed.is_vinyl,
                format_tokens=parsed.tokens,
                # The small image for lists, and the large one for enlarging a cover.
                cover_url=information.get("thumb") or None,
                cover_image_url=information.get("cover_image") or None,
                artist_discogs_id=_artist_id(information.get("artists") or ()),
            )
        )
    return items


def format_text(formats: list[dict]) -> str:
    """The format as the CSV export writes it, e.g. '2xLP, Album, RE, 180, Gat + CD'.

    The export keeps only the first three letters of the free text ('Blue, Gatefold'
    becomes 'Blu'); here the free text is searched for what the width needs instead.
    """
    segments = []
    for entry in formats:
        name = entry.get("name") or ""
        descriptions = list(entry.get("descriptions") or ())
        quantity = entry.get("qty") or "1"
        if name == "Vinyl":
            medium = next((size for size in _SIZES if size in descriptions), "Vinyl")
            descriptions = [d for d in descriptions if d not in _SIZES]
        else:
            medium = {"Box Set": "Box", "All Media": ""}.get(name, name)
        if medium and str(quantity).isdigit() and int(quantity) > 1:
            medium = f"{quantity}x{medium}"
        tokens = [medium] if medium else []
        tokens += [_ABBREVIATIONS.get(d, d) for d in descriptions if d not in _LEFT_OUT]
        text = (entry.get("text") or "").casefold()
        if "180" in text:
            tokens.append("180")
        if "gatefold" in text:
            tokens.append("Gat")
        if tokens:
            segments.append(", ".join(tokens))
    return " + ".join(segments)


def _artist_id(artists: list[dict]) -> int | None:
    """The Discogs artist of a release credited to exactly one artist."""
    if len(artists) != 1:
        return None
    artist_id = artists[0].get("id")
    return artist_id if artist_id and artist_id != VARIOUS_ARTISTS_ID else None


def _artist_name(artists: list[dict]) -> str:
    """The artists of a release as one name, joined the way the release credits them."""
    name = ""
    for artist in artists:
        name += (artist.get("name") or "").strip()
        join = (artist.get("join") or "").strip()
        if join:
            name += ", " if join == "," else f" {join} "
    return name.strip()
