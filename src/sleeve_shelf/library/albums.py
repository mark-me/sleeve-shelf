"""What the page of one album shows about it."""

from sleeve_shelf.domain import Album, Artist, Placement, ReleaseEnrichment, Style, find_by_id
from sleeve_shelf.library.taking_part import takes_part
from sleeve_shelf.persistence import BrowseQueries, JsonStore


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
