"""A round with Discogs as a background job: it runs for a long time, so not inside a request.

A round syncs the collection — fetches it page by page and takes it over — and then fetches
what the cache still lacks: styles, years and tracklists, artist pictures, and the images
themselves. It can also only fetch, after an export was imported.
"""

import threading
from collections.abc import Callable
from pathlib import Path

from sleeve_shelf.config import load_settings
from sleeve_shelf.fetching.discogs_import import import_discogs_collection
from sleeve_shelf.fetching.enrichment import enrich_collection
from sleeve_shelf.ingestion.discogs_api import (
    SECONDS_BETWEEN_IMAGES,
    SECONDS_BETWEEN_REQUESTS,
    DiscogsClient,
    DiscogsError,
    collection_items,
)
from sleeve_shelf.persistence import JsonStore

# done and total count the lookups of this run. part is what is being done now. collection
# is [pages fetched, pages] and releases how many the collection holds; synced is what
# taking it over did. albums, pictures and covers say how many of all of them are in:
# [done, total].
_IDLE = {
    "done": 0, "total": 0, "outcome": None, "error": None, "synced_round": False,
    "part": None, "collection": None, "releases": None, "synced": None,
    "albums": None, "pictures": None, "covers": None,
}


class _Stopped(Exception):
    """Raised inside the job when the user asked it to stop."""


class EnrichmentJob:
    """Runs one enrichment at a time and reports how far it is.

    The Discogs cache is saved along the way, so a job that is stopped — or lost with the process —
    continues from there when started again.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state = dict(_IDLE)

    def start(
        self, data_dir: Path, token: str, client_factory: Callable = DiscogsClient, sync: bool = False
    ) -> bool:
        """Start a round, unless one is already running.

        Args:
            data_dir: The data directory.
            token: The Discogs token.
            client_factory: Makes the Discogs client from the token.
            sync: The collection is fetched and taken over first.

        Returns:
            Whether a round was started.
        """
        with self._lock:
            if self.running:
                return False
            self._stop.clear()
            self._state = dict(_IDLE, synced_round=sync)
            self._thread = threading.Thread(
                target=self._run, args=(data_dir, token, client_factory, sync), daemon=True
            )
            self._thread.start()
            return True

    def stop(self) -> None:
        """Ask the round to stop."""
        self._stop.set()

    def wait(self, timeout: float | None = None) -> None:
        """Wait for the round to end.

        Args:
            timeout: How many seconds at most.
        """
        if self._thread is not None:
            self._thread.join(timeout)

    @property
    def running(self) -> bool:
        """Whether a round is running."""
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict:
        """How far the round is.

        Returns:
            Its state by name, with the seconds left.
        """
        state = dict(self._state)
        # Images are fetched faster than lookups, so the time left counts them apart.
        images = state["covers"][1] - state["covers"][0] if state["covers"] else 0
        lookups = max(state["total"] - state["done"] - images, 0)
        seconds = lookups * SECONDS_BETWEEN_REQUESTS + images * SECONDS_BETWEEN_IMAGES
        return {**state, "running": self.running, "seconds_left": round(seconds)}

    def _run(self, data_dir: Path, token: str, client_factory: Callable, sync: bool) -> None:
        def progress(done: int, total: int) -> None:
            self._state.update(done=done, total=total)
            if self._stop.is_set():
                raise _Stopped

        def part(name: str, done: int, total: int) -> None:
            self._state.update({"part": name, name: [done, total]})

        def page(fetched: int, pages: int, releases: int) -> None:
            self._state.update(part="collection", collection=[fetched, pages], releases=releases)
            if self._stop.is_set():
                raise _Stopped

        try:
            # A store of its own: a DuckDB connection is not shared between threads.
            store = JsonStore(data_dir)
            client = client_factory(token)
            if sync:
                self._state.update(part="collection", collection=[0, 0])
                releases = client.collection(page)
                if not releases:
                    self._state["outcome"] = "empty"
                    return
                # Taking it over never removes or moves anything: new albums stand on no
                # shelf, albums gone from Discogs are only marked, and matches it is not sure
                # of wait for the user. So it is taken over without asking first.
                self._state.update(part="import")
                settings = load_settings(data_dir)
                result = import_discogs_collection(
                    store,
                    collection_items(releases, settings.count_bonus_discs_as_vinyl),
                    settings.width_constants,
                    refresh_formats=True,
                )
                self._state["synced"] = {
                    "vinyl": result.vinyl_count,
                    "added": result.added,
                    "matched": result.matched,
                    "proposed": result.proposed,
                    "refreshed": result.refreshed,
                    "gone": len(result.gone),
                }
            enrich_collection(store, client, progress, part)
            self._state["outcome"] = "finished"
        except _Stopped:
            self._state["outcome"] = "stopped"
        except DiscogsError as error:
            self._state.update(outcome="failed", error=str(error))
        except Exception as error:  # noqa: BLE001 - the job must always report how it ended
            self._state.update(outcome="failed", error=f"{type(error).__name__}: {error}")
