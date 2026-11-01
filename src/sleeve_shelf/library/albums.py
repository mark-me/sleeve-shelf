"""What the page of one album shows about it."""

import hashlib
from pathlib import Path

from sleeve_shelf.domain import Album, Artist, Placement, ReleaseEnrichment, Style, find_by_id
from sleeve_shelf.library.images import MAX_IMAGE_BYTES, image_extension, thumb_name, thumbnail
from sleeve_shelf.library.taking_part import takes_part
from sleeve_shelf.persistence import BrowseQueries, JsonStore

OWN_COVER_DIR = "album_covers"


def album_details(store: JsonStore, album: Album, *, with_contents: bool = True) -> dict:
    """What the page of one album shows about it.

    Args:
        store: The store of the collection.
        album: The album.
        with_contents: False leaves out its styles and tracklist, for a tab that does not show them.

    Returns:
        What the page's template uses, by name.
    """
    placed = {p.album_id for p in store.load(Placement)}
    style_names = {style.id: style.name for style in store.load(Style)} if with_contents else {}
    releases = store.load(ReleaseEnrichment) if with_contents else []
    release = next((r for r in releases if r.release_id == album.release_id), None)
    return {
        "artist": find_by_id(store.load(Artist), album.artist_id),
        # Where the album stands, with its cluster and era band, comes from the same query as Browse.
        "row": next((r for r in BrowseQueries(store).artist_albums(album.artist_id) if r.album_id == album.id), None),
        "styles": [style_names[i] for i in album.style_ids if i in style_names],
        # None while the release was not fetched with its tracklist yet.
        "tracklist": release.tracklist if release else None,
        "takes_part": takes_part(album, placed),
        "is_placed": album.id in placed,
    }


def set_own_cover(store: JsonStore, album_id: int, data: bytes) -> bool:
    """Keep the user's own cover of an album; it is shown instead of the one from Discogs.

    The file goes into the data directory, under a name that changes with its contents, with a
    small copy for the lists. A sync leaves it alone.

    Args:
        store: The store of the collection.
        album_id: The album.
        data: The bytes of the image.

    Returns:
        False when the bytes are no image the app can show, or are too large, or there is no
        such album.
    """
    extension = image_extension(data)
    if extension is None or len(data) > MAX_IMAGE_BYTES:
        return False
    small = thumbnail(data)
    albums = store.load(Album)
    album = find_by_id(albums, album_id)
    if small is None or album is None:
        return False
    directory = Path(store.data_dir) / OWN_COVER_DIR
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{album_id}-{hashlib.sha1(data).hexdigest()[:10]}.{extension}"
    partial = directory / (name + ".part")
    partial.write_bytes(data)
    partial.replace(directory / name)
    (directory / thumb_name(name)).write_bytes(small)
    if album.own_cover_file and album.own_cover_file != name:
        _remove_cover_files(directory, album.own_cover_file)
    album.own_cover_file = name
    store.save(Album, albums)
    return True


def remove_own_cover(store: JsonStore, album_id: int) -> None:
    """Take the user's own cover away again; the one from Discogs, if any, shows once more.

    Args:
        store: The store of the collection.
        album_id: The album.
    """
    albums = store.load(Album)
    album = find_by_id(albums, album_id)
    if album is None or not album.own_cover_file:
        return
    _remove_cover_files(Path(store.data_dir) / OWN_COVER_DIR, album.own_cover_file)
    album.own_cover_file = None
    store.save(Album, albums)


def _remove_cover_files(directory: Path, name: str) -> None:
    (directory / name).unlink(missing_ok=True)
    (directory / thumb_name(name)).unlink(missing_ok=True)
