"""Application services for saved versions of the layout."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from sleeve_shelf.domain import Album, Placement, Shelf
from sleeve_shelf.persistence import JsonStore

STAMP = "%Y%m%d-%H%M%S"
# While editing by hand, a restore point is kept at most this often.
RESTORE_POINT_EVERY = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class Version:
    name: str
    saved_at: datetime
    label: str
    album_count: int
    is_current: bool


def list_versions(store: JsonStore) -> list[Version]:
    """The saved versions, newest first."""
    versions = []
    for name in store.snapshots():
        stamp, _, slug = name.partition("--")
        try:
            saved_at = datetime.strptime(stamp, STAMP)
        except ValueError:
            continue
        versions.append(
            Version(
                name,
                saved_at,
                slug.replace("-", " "),
                len(store.load_snapshot(name)),
                store.snapshot_is_current(name),
            )
        )
    return sorted(versions, key=lambda version: version.name, reverse=True)


def save_version(store: JsonStore, label: str = "") -> str:
    """Save the current layout as a version, optionally under a short label."""
    slug = re.sub(r"[^a-z0-9]+", "-", label.casefold()).strip("-")
    base = datetime.now().strftime(STAMP)
    taken = set(store.snapshots())
    name, attempt = (f"{base}--{slug}" if slug else base), 1
    while name in taken:
        attempt += 1
        name = f"{base}--{slug}-{attempt}" if slug else f"{base}--{attempt}"
    store.save_snapshot(name)
    return name


def _latest(store: JsonStore) -> Version | None:
    return next(iter(list_versions(store)), None)


def save_if_unsaved(store: JsonStore, label: str) -> None:
    """Keep the current layout as a version unless the newest version already is it."""
    if not store.exists(Placement):
        return
    latest = _latest(store)
    if latest is None or not latest.is_current:
        save_version(store, label)


def keep_restore_point(store: JsonStore) -> None:
    """Called before a change by hand: make sure there is a recent version to go back to.

    A layout that is saved already needs nothing. One with unsaved changes is
    saved when the newest version is older than an hour, so an editing session
    always starts from a restore point without filling the list with every move.
    """
    latest = _latest(store)
    if latest is None or (
        not latest.is_current and datetime.now() - latest.saved_at >= RESTORE_POINT_EVERY
    ):
        save_version(store, "before editing")


def restore_version(store: JsonStore, name: str) -> int:
    """Make a saved version the current layout; returns how many of its albums could not return.

    The layout as it is now is saved first when it wasn't, so restoring can be undone.
    Albums and shelves that no longer exist are left out.
    """
    if name not in store.snapshots():
        return 0
    placements = store.load_snapshot(name)
    save_if_unsaved(store, "before restoring")
    album_ids = {album.id for album in store.load(Album)}
    shelf_ids = {shelf.id for shelf in store.load(Shelf)}
    kept = [p for p in placements if p.album_id in album_ids and p.shelf_id in shelf_ids]
    store.save(Placement, kept)
    return len(placements) - len(kept)
