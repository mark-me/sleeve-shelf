"""Application service for album covers and artist pictures kept in the data directory."""

import hashlib
from collections.abc import Callable, Iterable
from pathlib import Path

from sleeve_shelf.domain import Album, ArtistEnrichment
from sleeve_shelf.ingestion.discogs_api import DiscogsClient
from sleeve_shelf.persistence import JsonStore

COVER_DIR = "covers"
# An image Discogs no longer has is marked with an empty file of this kind, so it is not
# asked for again at every run.
MISSING = ".missing"


def cover_name(url: str) -> str:
    """The file an image is kept under: named after its address, so a new address is a new file."""
    return hashlib.sha1(url.encode()).hexdigest()[:20] + ".jpg"


def stored_names(data_dir: Path) -> set[str]:
    """The names of everything in the cover directory, images and "missing" marks alike."""
    directory = Path(data_dir) / COVER_DIR
    return {path.name for path in directory.iterdir()} if directory.is_dir() else set()


def image_urls(albums: Iterable[Album], pictures: Iterable[ArtistEnrichment]) -> list[str]:
    """Every image the pages show, each once: small covers first, then large ones, then artists."""
    albums = list(albums)
    pictures = list(pictures)
    urls = [album.cover_url for album in albums]
    urls += [album.cover_image_url for album in albums]
    urls += [picture.thumb_url for picture in pictures]
    urls += [picture.image_url for picture in pictures]
    return list(dict.fromkeys(url for url in urls if url))


def missing_images(
    store: JsonStore,
    albums: Iterable[Album] | None = None,
    pictures: Iterable[ArtistEnrichment] | None = None,
) -> list[str]:
    """The images not yet in the data directory, and not marked as gone at Discogs."""
    stored = stored_names(store.data_dir)
    return [
        url
        for url in image_urls(
            store.load(Album) if albums is None else albums,
            store.load(ArtistEnrichment) if pictures is None else pictures,
        )
        if cover_name(url) not in stored
        and cover_name(url).replace(".jpg", MISSING) not in stored
    ]


def download_images(
    store: JsonStore,
    client: DiscogsClient,
    urls: list[str],
    progress: Callable[[int], None] = lambda count: None,
) -> int:
    """Fetch the images into the data directory; returns how many came in.

    An image Discogs no longer has is marked as such and skipped from then on.
    Each file is written whole or not at all, so a run that is stopped — the
    progress callback may raise to stop it — leaves nothing half-written.
    """
    directory = store.data_dir / COVER_DIR
    directory.mkdir(parents=True, exist_ok=True)
    fetched = 0
    for count, url in enumerate(urls, start=1):
        data = client.image(url)
        target = directory / cover_name(url)
        if data:
            partial = target.with_suffix(".part")
            partial.write_bytes(data)
            partial.replace(target)
            fetched += 1
        else:
            target.with_suffix(MISSING).touch()
        progress(count)
    return fetched
