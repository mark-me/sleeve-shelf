"""Application services for curating an artist: start year, cluster and picture."""

import hashlib
from collections import Counter
import io
from pathlib import Path

from PIL import Image, ImageOps

from sleeve_shelf.collection import ensure_cluster_order
from sleeve_shelf.domain import Album, Artist, ArtistClusterAssignment, Cluster, find_by_id
from sleeve_shelf.persistence import JsonStore


def set_start_year(store: JsonStore, artist_id: int, year: int | None) -> None:
    """Set the year the artist began; None lets the collection's earliest year stand in again."""
    artists = store.load(Artist)
    for artist in artists:
        if artist.id == artist_id:
            artist.start_year = year
    store.save(Artist, artists)


def set_cluster(
    store: JsonStore, artist_id: int, cluster_id: int | None, new_cluster_name: str = ""
) -> None:
    """Put the artist in a cluster — an existing one, or a new one by name — as confirmed.

    With neither, the artist has no cluster of its own choosing and one is proposed again.
    """
    assignments = [a for a in store.load(ArtistClusterAssignment) if a.artist_id != artist_id]
    if new_cluster_name:
        clusters = store.load(Cluster)
        existing = next(
            (c for c in clusters if c.name.casefold() == new_cluster_name.casefold()), None
        )
        if existing is None:
            existing = Cluster(store.next_id(Cluster, clusters), new_cluster_name)
            clusters.append(existing)
            store.save(Cluster, clusters)
            ensure_cluster_order(store)
        cluster_id = existing.id
    if cluster_id is not None:
        assignments.append(ArtistClusterAssignment(artist_id, cluster_id, confirmed=True))
    store.save(ArtistClusterAssignment, assignments)
    _clear_purchases(store, artist_id)


def confirm_cluster(store: JsonStore, artist_id: int) -> None:
    """Confirm the cluster that was proposed for the artist."""
    assignments = store.load(ArtistClusterAssignment)
    for assignment in assignments:
        if assignment.artist_id == artist_id:
            assignment.confirmed = True
    store.save(ArtistClusterAssignment, assignments)
    _clear_purchases(store, artist_id)


def _clear_purchases(store: JsonStore, artist_id: int) -> None:
    """A decision on the artist's cluster was taken, so its purchases need no weighing any more."""
    albums = store.load(Album)
    marked = [a for a in albums if a.artist_id == artist_id and a.new_purchase]
    if marked:
        for album in marked:
            album.new_purchase = False
        store.save(Album, albums)


PICTURE_DIR = "artist_pictures"
MAX_PICTURE_BYTES = 5 * 1024 * 1024
# The longest side of the small copy made for lists: twice the 150 px a picture is shown at
# on the artist's page, so it stays sharp on a phone.
THUMB_PIXELS = 300
# What an image file starts with, and the extension it is kept under.
_IMAGE_KINDS = (
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)


def picture_extension(data: bytes) -> str | None:
    """The kind of image the bytes are — JPEG, PNG, GIF or WebP — or None for anything else."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return next((ext for start, ext in _IMAGE_KINDS if data.startswith(start)), None)


def thumb_name(picture_file: str) -> str:
    """The file the small copy of a picture is kept under, next to the picture itself."""
    return Path(picture_file).stem + ".thumb.jpg"


def _thumbnail(data: bytes) -> bytes | None:
    """A small JPEG copy of an image, upright and without transparency; None if it can't be read."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((THUMB_PIXELS, THUMB_PIXELS))
            if image.mode != "RGB":
                # JPEG has no transparency: lay the picture on white.
                image = image.convert("RGBA")
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            out = io.BytesIO()
            image.save(out, "JPEG", quality=85, optimize=True)
            return out.getvalue()
    except Exception:  # noqa: BLE001 - whatever is wrong with the file, it is no usable image
        return None


def picture_thumb(store: JsonStore, artist: Artist) -> str | None:
    """The small copy of the user's own picture, made now if a picture from before has none.

    Returns its file name, or the picture's own when no small copy can be made.
    """
    if not artist.picture_file:
        return None
    directory = Path(store.data_dir) / PICTURE_DIR
    name = thumb_name(artist.picture_file)
    if (directory / name).exists():
        return name
    source = directory / artist.picture_file
    small = _thumbnail(source.read_bytes()) if source.exists() else None
    if small is None:
        return artist.picture_file
    (directory / name).write_bytes(small)
    return name


def set_picture(store: JsonStore, artist_id: int, data: bytes) -> bool:
    """Keep the user's own picture of an artist; it is shown instead of the one from Discogs.

    The file goes into the data directory, apart from the images downloaded from
    Discogs, under a name that changes with its contents. Returns False when the
    bytes are no image the app can show, or are too large. A small copy is
    made at once, for the lists: those never load the picture in full.
    """
    extension = picture_extension(data)
    if extension is None or len(data) > MAX_PICTURE_BYTES:
        return False
    small = _thumbnail(data)
    if small is None:
        return False
    artists = store.load(Artist)
    artist = find_by_id(artists, artist_id)
    if artist is None:
        return False
    directory = Path(store.data_dir) / PICTURE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{artist_id}-{hashlib.sha1(data).hexdigest()[:10]}.{extension}"
    partial = directory / (name + ".part")
    partial.write_bytes(data)
    partial.replace(directory / name)
    (directory / thumb_name(name)).write_bytes(small)
    if artist.picture_file and artist.picture_file != name:
        (directory / artist.picture_file).unlink(missing_ok=True)
        (directory / thumb_name(artist.picture_file)).unlink(missing_ok=True)
    artist.picture_file = name
    store.save(Artist, artists)
    return True


def remove_picture(store: JsonStore, artist_id: int) -> None:
    """Take the user's own picture away again; the one from Discogs, if any, shows once more."""
    artists = store.load(Artist)
    artist = find_by_id(artists, artist_id)
    if artist is None or not artist.picture_file:
        return
    directory = Path(store.data_dir) / PICTURE_DIR
    (directory / artist.picture_file).unlink(missing_ok=True)
    (directory / thumb_name(artist.picture_file)).unlink(missing_ok=True)
    artist.picture_file = None
    store.save(Artist, artists)


def albums_per_artist(store: JsonStore) -> Counter[int]:
    """How many albums each artist has in the collection, singles included."""
    return Counter(album.artist_id for album in store.load(Album))
