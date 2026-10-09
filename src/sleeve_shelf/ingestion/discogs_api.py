"""Client for the Discogs API: the collection, and the release and master lookups."""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime

from sleeve_shelf.domain import MasterEnrichment, ReleaseEnrichment
from sleeve_shelf.ingestion.discogs_csv import CollectionItem
from sleeve_shelf.ingestion.formats import parse_format

API_ROOT = "https://api.discogs.com"
USER_AGENT = "SleeveShelf/0.1 +https://github.com/mark-me/sleeve-shelf"
# Authenticated requests are limited to 60 per minute.
SECONDS_BETWEEN_REQUESTS = 1.05
RATE_LIMIT_PAUSE_SECONDS = 60
MAX_ATTEMPTS = 3
COLLECTION_PAGE_SIZE = 100

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
        """Styles, master and year of a release; one that no longer exists yields none."""
        data = self._get(f"/releases/{release_id}") or {}
        return ReleaseEnrichment(
            release_id=release_id,
            styles=tuple(data.get("styles") or ()),
            master_id=data.get("master_id") or None,
            fetched_at=datetime.now().replace(microsecond=0),
            year=data.get("year") or None,
        )

    def master(self, master_id: int) -> MasterEnrichment:
        """The original release year of a master."""
        data = self._get(f"/masters/{master_id}") or {}
        return MasterEnrichment(
            master_id=master_id,
            original_release_year=data.get("year") or None,
            fetched_at=datetime.now().replace(microsecond=0),
        )

    def collection(self) -> list[dict]:
        """Every release in the collection of the token's owner, as the API gives them."""
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
            if page >= (data.get("pagination") or {}).get("pages", 1):
                return releases
            page += 1

    def _get(self, path: str) -> dict | None:
        request = urllib.request.Request(
            API_ROOT + path,
            headers={
                "Authorization": f"Discogs token={self._token}",
                "User-Agent": USER_AGENT,
            },
        )
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

    def _pace(self) -> None:
        now = self._clock()
        if self._last_request is not None:
            wait = SECONDS_BETWEEN_REQUESTS - (now - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._clock()


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


def _artist_name(artists: list[dict]) -> str:
    """The artists of a release as one name, joined the way the release credits them."""
    name = ""
    for artist in artists:
        name += (artist.get("name") or "").strip()
        join = (artist.get("join") or "").strip()
        if join:
            name += ", " if join == "," else f" {join} "
    return name.strip()
