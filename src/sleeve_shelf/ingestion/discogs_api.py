"""Client for the two Discogs API lookups the enrichment needs: release and master."""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime

from sleeve_shelf.domain import MasterEnrichment, ReleaseEnrichment

API_ROOT = "https://api.discogs.com"
USER_AGENT = "SleeveShelf/0.1 +https://github.com/mark-me/sleeve-shelf"
# Authenticated requests are limited to 60 per minute.
SECONDS_BETWEEN_REQUESTS = 1.05
RATE_LIMIT_PAUSE_SECONDS = 60
MAX_ATTEMPTS = 3


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
