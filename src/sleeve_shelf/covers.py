"""Application service for album covers and artist pictures kept in the data directory."""

import hashlib
from collections.abc import Callable, Iterable
from pathlib import Path

from sleeve_shelf.domain import Album, ArtistEnrichment
from sleeve_shelf.ingestion.discogs_api import DiscogsClient
from sleeve_shelf.persistence import JsonStore

COVER_DIR = "covers"
# Within it, the album covers and the artist pictures each have a folder of their own.
ALBUM_DIR = "albums"
ARTIST_DIR = "artists"
# An image Discogs no longer has is marked with an empty file of this kind, so it is not
# asked for again at every run.
MISSING = ".missing"


def cover_name(url: str) -> str:
    """The file an image is kept under: named after its address, so a new address is a new file."""
    return hashlib.sha1(url.encode()).hexdigest()[:20] + ".jpg"


def stored_names(data_dir: Path) -> set[str]:
    """Everything stored, images and "missing" marks alike, as "folder/name"."""
    names: set[str] = set()
    for folder in (ALBUM_DIR, ARTIST_DIR):
        directory = Path(data_dir) / COVER_DIR / folder
        if directory.is_dir():
            names.update(f"{folder}/{path.name}" for path in directory.iterdir())
    return names


def image_paths(albums: Iterable[Album], pictures: Iterable[ArtistEnrichment]) -> dict[str, str]:
    """Per image the pages show: where it is kept, as "folder/name", in the order of image_urls."""
    albums = list(albums)
    pictures = list(pictures)
    of_albums = {url for album in albums for url in (album.cover_url, album.cover_image_url)}
    return {
        url: f"{ALBUM_DIR if url in of_albums else ARTIST_DIR}/{cover_name(url)}"
        for url in image_urls(albums, pictures)
    }


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
    paths = image_paths(
        store.load(Album) if albums is None else albums,
        store.load(ArtistEnrichment) if pictures is None else pictures,
    )
    return [
        url
        for url, path in paths.items()
        if path not in stored and path.replace(".jpg", MISSING) not in stored
    ]


def download_images(
    store: JsonStore,
    client: DiscogsClient,
    urls: list[str],
    progress: Callable[[int], None] = lambda count: None,
) -> int:
    """Fetch the images into the data directory; returns how many came in.

    A cover goes into the folder of the albums, an artist's picture into that of the
    artists. An image Discogs no longer has is marked as such and skipped from then on.
    Each file is written whole or not at all, so a run that is stopped — the
    progress callback may raise to stop it — leaves nothing half-written.
    """
    directory = store.data_dir / COVER_DIR
    paths = image_paths(store.load(Album), store.load(ArtistEnrichment))
    for folder in (ALBUM_DIR, ARTIST_DIR):
        (directory / folder).mkdir(parents=True, exist_ok=True)
    fetched = 0
    for count, url in enumerate(urls, start=1):
        data = client.image(url)
        # An address no album has is an artist's: albums are the ones that come and go.
        target = directory / paths.get(url, f"{ARTIST_DIR}/{cover_name(url)}")
        if data:
            partial = target.with_suffix(".part")
            partial.write_bytes(data)
            partial.replace(target)
            fetched += 1
        else:
            target.with_suffix(MISSING).touch()
        progress(count)
    return fetched


def sort_into_folders(store: JsonStore) -> int:
    """Move images stored before covers and pictures had folders of their own into them.

    Returns how many files were moved. A file no album or artist points to any more
    stays where it is: nothing is removed.
    """
    directory = store.data_dir / COVER_DIR
    loose = [path for path in directory.iterdir() if path.is_file()] if directory.is_dir() else []
    if not loose:
        return 0
    folder_of = {
        Path(path).name: Path(path).parent.name
        for path in image_paths(store.load(Album), store.load(ArtistEnrichment)).values()
    }
    moved = 0
    for path in loose:
        folder = folder_of.get(path.with_suffix(".jpg").name)
        if folder is None or path.suffix not in (".jpg", MISSING):
            continue
        (directory / folder).mkdir(exist_ok=True)
        path.replace(directory / folder / path.name)
        moved += 1
    return moved
