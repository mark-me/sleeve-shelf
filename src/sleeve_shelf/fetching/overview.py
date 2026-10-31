"""What the Discogs screen says: how far the collection is fetched, and what waits for a decision."""

from math import ceil

from sleeve_shelf.domain import Album, Artist, ArtistEnrichment, MatchProposal, ReleaseEnrichment
from sleeve_shelf.fetching.covers import image_paths, missing_images, stored_names
from sleeve_shelf.fetching.enrichment import releases_to_fetch
from sleeve_shelf.ingestion.discogs_api import SECONDS_BETWEEN_IMAGES, SECONDS_BETWEEN_REQUESTS
from sleeve_shelf.persistence import JsonStore


def fetch_overview(store: JsonStore) -> dict:
    """The counts and lists of the Discogs screen, with how far each part is as [done, total]."""
    albums = store.load(Album)
    artist_list = store.load(Artist)
    artists = {artist.id: artist.name for artist in artist_list}
    linked = {album.release_id for album in albums if album.release_id is not None}
    # A release fetched before tracklists were kept is asked for again, for its tracklist.
    new_ids, tracklist_ids = releases_to_fetch(
        albums, {release.release_id: release for release in store.load(ReleaseEnrichment)}
    )
    to_fetch = new_ids | tracklist_ids
    by_id = {album.id: album for album in albums}
    named = {a.discogs_artist_id for a in artist_list if a.discogs_artist_id is not None}
    pictures = store.load(ArtistEnrichment)
    pictures_by_id = {p.discogs_artist_id: p for p in pictures}
    pictured = set(pictures_by_id)
    images = image_paths(albums, pictures)
    images_missing = len(missing_images(store, albums, pictures))
    names = stored_names(store.data_dir)
    images_stored = sum(path in names for path in images.values())
    to_fetch_pictures = sum(
        1
        for a in artist_list
        if a.discogs_artist_id is not None
        and (
            a.discogs_artist_id not in pictures_by_id
            or pictures_by_id[a.discogs_artist_id].member_ids is None
        )
    )
    return {
        "album_count": len(albums),
        "linked_count": sum(album.release_id is not None for album in albums),
        "fetched_count": len(linked - to_fetch),
        "to_fetch_count": len(to_fetch),
        # Whether anything is left to fetch, which a round would do.
        "fetch_open": bool(to_fetch or to_fetch_pictures or images_missing),
        "pictures_to_fetch_count": to_fetch_pictures,
        "albums_progress": [len(linked - to_fetch), len(linked)],
        "pictures_progress": [len(named & pictured), len(named)],
        "covers_to_fetch_count": images_missing,
        "covers_progress": [images_stored, len(images)],
        "covers_gone_count": len(images) - images_stored - images_missing,
        "unnamed_count": sum(artist.discogs_artist_id is None for artist in artist_list),
        "minutes": ceil(
            (
                (2 * len(new_ids) + len(tracklist_ids) + len(named - pictured))
                * SECONDS_BETWEEN_REQUESTS
                # Covers and pictures that are still to be named come on top of these.
                + images_missing * SECONDS_BETWEEN_IMAGES
            )
            / 60
        ),
        "seconds_per_lookup": SECONDS_BETWEEN_REQUESTS,
        "proposals": [
            {
                "proposal": proposal,
                "album_artist": artists.get(by_id[proposal.album_id].artist_id, ""),
                "album_title": by_id[proposal.album_id].title,
            }
            for proposal in store.load(MatchProposal)
            if proposal.album_id in by_id
        ],
        "gone": [
            {"album": album, "artist": artists.get(album.artist_id, "")}
            for album in albums
            if album.left_discogs and not album.kept_after_discogs
        ],
        "kept": [
            {"album": album, "artist": artists.get(album.artist_id, "")}
            for album in albums
            if album.left_discogs and album.kept_after_discogs
        ],
    }
