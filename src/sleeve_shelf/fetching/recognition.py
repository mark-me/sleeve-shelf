"""Which album a photo of a sleeve shows: looked up among the covers kept in the data directory.

The features of every cover are kept in one file next to the covers, so they are worked out once:
after that only a cover that is new is described, and one that is gone left out. A photo is never
kept.
"""

import io
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from sleeve_shelf.domain import Album
from sleeve_shelf.fetching.covers import ALBUM_DIR, COVER_DIR, cover_name
from sleeve_shelf.ingestion.cover_matching import CoverIndex, Described, describe_cover, is_sure
from sleeve_shelf.library.albums import OWN_COVER_DIR
from sleeve_shelf.library.images import image_extension
from sleeve_shelf.persistence import JsonStore

# A photo from a phone is a few MB; a camera of 50 megapixels makes one of up to some 15.
MAX_PHOTO_BYTES = 16 * 1024 * 1024
# Larger than any phone's photo, and too large to decode safely.
MAX_PHOTO_PIXELS = 64_000_000
# Read smaller than taken: recognising looks at 900 px, so twice that is plenty.
READ_PIXELS = 1800
PHOTO_KINDS = frozenset({"jpg", "png", "webp"})
# The file that keeps the features of the covers, next to them.
FEATURES_FILE = "recognition.npz"


@dataclass(frozen=True)
class Recognition:
    """What a photo shows.

    Attributes:
        readable: False for a file that is no photo that can be read.
        album_ids: The albums it may show, the likeliest first; none when nothing was recognised.
        sure: Whether the first is recognised with certainty.
    """

    readable: bool
    album_ids: tuple[int, ...] = ()
    sure: bool = False


def recognise(store: JsonStore, data: bytes) -> Recognition:
    """Which album a photo shows.

    Args:
        store: The store of the collection.
        data: The bytes of the photo.

    Returns:
        What it shows.
    """
    gray = read_photo(data)
    if gray is None:
        return Recognition(readable=False)
    index, lock = _index(store)
    with lock:
        candidates = index.candidates(gray)
    return Recognition(True, tuple(c.album_id for c in candidates), is_sure(candidates))


def read_photo(data: bytes) -> np.ndarray | None:
    """A photo in grey, upright and no larger than recognising needs.

    The photo comes from anyone, so it is checked before it is decoded: its kind by its first
    bytes, its size, and its number of pixels.

    Args:
        data: The bytes of the photo.

    Returns:
        The photo as an array of rows of grey pixels; None for anything that can't be read.
    """
    if len(data) > MAX_PHOTO_BYTES or image_extension(data) not in PHOTO_KINDS:
        return None
    try:
        with Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as image:
            if image.width * image.height > MAX_PHOTO_PIXELS:
                return None
            # A JPEG is decoded at a fraction of its size straight away, which is much faster.
            image.draft("L", (READ_PIXELS, READ_PIXELS))
            image = ImageOps.exif_transpose(image).convert("L")
            image.thumbnail((READ_PIXELS, READ_PIXELS))
            return np.asarray(image)
    except Exception:  # noqa: BLE001 - whatever is wrong with the file, it is no usable photo
        return None


# Per data directory: the covers the index was made of, the index, and the lock for using it.
_indexes: dict[Path, tuple[tuple[str, ...], CoverIndex, threading.Lock]] = {}
_building = threading.Lock()


def _index(store: JsonStore) -> tuple[CoverIndex, threading.Lock]:
    """The index of the covers as they are kept now, made anew only when they changed."""
    covers = _covers(store)
    keys = tuple(sorted(covers))
    data_dir = Path(store.data_dir)
    with _building:
        kept = _indexes.get(data_dir)
        if kept is None or kept[0] != keys:
            described = _described(data_dir, covers)
            kept = (keys, CoverIndex(described), threading.Lock())
            _indexes[data_dir] = kept
    return kept[1], kept[2]


def _covers(store: JsonStore) -> dict[str, tuple[int, Path]]:
    """Every cover kept for an album, by a key naming the album and the file.

    The large cover from Discogs, else the small one, and a cover of the user's own besides: both
    show the sleeve, so both may be recognised.
    """
    data_dir = Path(store.data_dir)
    covers: dict[str, tuple[int, Path]] = {}
    for album in store.load(Album):
        for url in (album.cover_image_url, album.cover_url):
            path = data_dir / COVER_DIR / ALBUM_DIR / cover_name(url) if url and url.startswith("http") else None
            if path is not None and path.is_file():
                covers[f"{album.id}/{path.name}"] = (album.id, path)
                break
        if album.own_cover_file:
            path = data_dir / OWN_COVER_DIR / album.own_cover_file
            if path.is_file():
                covers[f"{album.id}/{path.name}"] = (album.id, path)
    return covers


def _described(data_dir: Path, covers: dict[str, tuple[int, Path]]) -> list[Described]:
    """The features of every cover: those kept already, and the new ones worked out and kept."""
    file = data_dir / COVER_DIR / FEATURES_FILE
    kept = _read_features(file)
    described = {key: kept[key] for key in covers if key in kept}
    for key in sorted(set(covers) - set(described)):
        album_id, path = covers[key]
        gray = _cover_in_grey(path)
        found = describe_cover(album_id, gray) if gray is not None else None
        # A cover with too little on it is kept as such, so it is not looked at again each time.
        described[key] = found or Described(album_id, np.zeros((0, 2), np.float32), np.zeros((0, 32), np.uint8))
    if set(described) != set(kept):
        _write_features(file, described)
    return [described[key] for key in sorted(described)]


def _cover_in_grey(path: Path) -> np.ndarray | None:
    try:
        with Image.open(path) as image:
            return np.asarray(image.convert("L"))
    except Exception:  # noqa: BLE001 - a damaged file is a cover that can't be recognised
        return None


def _read_features(file: Path) -> dict[str, Described]:
    """The features kept in the file; none when there is no file or it can't be read."""
    try:
        with np.load(file, allow_pickle=False) as kept:
            keys, counts = kept["keys"], kept["counts"]
            points, descriptors = kept["points"], kept["descriptors"]
    except (OSError, KeyError, ValueError):
        return {}
    found, start = {}, 0
    for key, count in zip(keys, counts):
        end = start + int(count)
        album_id = int(str(key).split("/", 1)[0])
        found[str(key)] = Described(album_id, points[start:end], descriptors[start:end])
        start = end
    return found


def _write_features(file: Path, described: dict[str, Described]) -> None:
    """Keep the features in one file, written whole or not at all."""
    keys = sorted(described)
    file.parent.mkdir(parents=True, exist_ok=True)
    partial = file.with_name(file.name + ".part")
    with partial.open("wb") as out:
        np.savez(
            out,
            keys=np.array(keys),
            counts=np.array([len(described[key].descriptors) for key in keys], dtype=np.int64),
            points=np.concatenate([described[key].points for key in keys]) if keys else np.zeros((0, 2), np.float32),
            descriptors=(
                np.concatenate([described[key].descriptors for key in keys]) if keys else np.zeros((0, 32), np.uint8)
            ),
        )
    partial.replace(file)
