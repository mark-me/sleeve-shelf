"""Application service for album covers and artist pictures kept in the data directory."""

import hashlib
import io
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from PIL import Image

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
# Discogs' own small image is 150 px at a low JPEG quality, which shows as grain. Once the
# large image is in, the small one is made afresh from it: twice the 150 px a cover is
# shown at on its page, so it stays sharp on a phone. A small image wider or higher than
# Discogs' is therefore one made here.
DISCOGS_SMALL_PIXELS = 150
SMALL_PIXELS = 300
SMALL_QUALITY = 85
REPLACE_ATTEMPTS = 6


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


def image_pairs(albums: Iterable[Album], pictures: Iterable[ArtistEnrichment]) -> dict[str, str]:
    """Per small image the address of its large one, for those that have both."""
    pairs = {album.cover_url: album.cover_image_url for album in albums}
    pairs.update({picture.thumb_url: picture.image_url for picture in pictures})
    return {small: large for small, large in pairs.items() if small and large and small != large}


def _sharpen(small: Path, large: Path) -> bool:
    """Make the small image afresh from the large one; False when that is not needed or possible."""
    try:
        with Image.open(small) as image:
            if max(image.size) > DISCOGS_SMALL_PIXELS:
                return False
        with Image.open(large) as image:
            if max(image.size) <= DISCOGS_SMALL_PIXELS:
                # A "large" image no bigger than the small one has nothing to add.
                return False
            image = image.convert("RGB")
            image.thumbnail((SMALL_PIXELS, SMALL_PIXELS))
            out = io.BytesIO()
            image.save(out, "JPEG", quality=SMALL_QUALITY, optimize=True)
    except Exception:  # noqa: BLE001 - a file that is no readable image keeps what it has
        return False
    # A name of its own, as the app may be making these aside while a fetch run does too.
    partial = small.with_suffix(f".{threading.get_ident()}.part")
    partial.write_bytes(out.getvalue())
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            partial.replace(small)
            return True
        except PermissionError:
            # On Windows a file that is being read or scanned cannot be replaced right then.
            time.sleep(0.05 * (attempt + 1))
    partial.unlink(missing_ok=True)
    return False


def sharpen_small_images(store: JsonStore) -> int:
    """Replace Discogs' grainy small images by copies made from the stored large ones.

    Only where both are stored, and only once: an image made here is recognised by
    its size. Returns how many were made. Nothing is fetched.
    """
    directory = store.data_dir / COVER_DIR
    stored = stored_names(store.data_dir)
    albums, pictures = store.load(Album), store.load(ArtistEnrichment)
    paths = image_paths(albums, pictures)
    made = 0
    for small, large in image_pairs(albums, pictures).items():
        if paths[small] in stored and paths[large] in stored:
            made += _sharpen(directory / paths[small], directory / paths[large])
    return made


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
    albums, pictures = store.load(Album), store.load(ArtistEnrichment)
    paths = image_paths(albums, pictures)
    small_of = {large: small for small, large in image_pairs(albums, pictures).items()}
    large_of = {small: large for large, small in small_of.items()}
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
            # With both sizes in, the small one is made afresh from the large one.
            small = url if url in large_of else small_of.get(url)
            if small in paths and large_of[small] in paths:
                _sharpen(directory / paths[small], directory / paths[large_of[small]])
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
