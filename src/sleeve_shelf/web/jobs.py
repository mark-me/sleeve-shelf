"""The enrichment as a background job: it runs for a long time, so not inside a request."""

import threading
from collections.abc import Callable
from pathlib import Path

from sleeve_shelf.collection import enrich_collection
from sleeve_shelf.ingestion.discogs_api import DiscogsClient, DiscogsError
from sleeve_shelf.persistence import JsonStore


class _Stopped(Exception):
    """Raised inside the job when the user asked it to stop."""


class EnrichmentJob:
    """Runs one enrichment at a time and reports how far it is.

    The Discogs cache is saved along the way, so a job that is stopped — or
    lost with the process — continues from there when started again.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state = {"done": 0, "total": 0, "outcome": None, "error": None}

    def start(
        self, data_dir: Path, token: str, client_factory: Callable = DiscogsClient
    ) -> bool:
        """Start the job unless one is already running."""
        with self._lock:
            if self.running:
                return False
            self._stop.clear()
            self._state = {"done": 0, "total": 0, "outcome": None, "error": None}
            self._thread = threading.Thread(
                target=self._run, args=(data_dir, token, client_factory), daemon=True
            )
            self._thread.start()
            return True

    def stop(self) -> None:
        self._stop.set()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict:
        return {**self._state, "running": self.running}

    def _run(self, data_dir: Path, token: str, client_factory: Callable) -> None:
        def progress(done: int, total: int) -> None:
            self._state.update(done=done, total=total)
            if self._stop.is_set():
                raise _Stopped

        try:
            # A store of its own: a DuckDB connection is not shared between threads.
            enrich_collection(JsonStore(data_dir), client_factory(token), progress)
            self._state["outcome"] = "finished"
        except _Stopped:
            self._state["outcome"] = "stopped"
        except DiscogsError as error:
            self._state.update(outcome="failed", error=str(error))
        except Exception as error:  # noqa: BLE001 - the job must always report how it ended
            self._state.update(outcome="failed", error=f"{type(error).__name__}: {error}")
