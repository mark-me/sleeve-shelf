"""Application services for enriching the collection from Discogs: styles, original years
and artist pictures fetched and cached, then applied to the albums and artists."""

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import replace

from sleeve_shelf.collection import ensure_cluster_order
from sleeve_shelf.covers import download_images, image_urls, missing_images
from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    ArtistEnrichment,
    Cluster,
    MasterEnrichment,
    ReleaseEnrichment,
    Style,
)
from sleeve_shelf.ingestion.discogs_api import DiscogsClient
from sleeve_shelf.persistence import JsonStore

SAVE_CACHE_EVERY = 25


def releases_to_fetch(
    albums: Iterable[Album], releases: dict[int, ReleaseEnrichment]
) -> tuple[set[int], set[int]]:
    """The releases of the albums still to be asked for: those never fetched, and those
    fetched before tracklists, or the writers of their songs, were kept, which are asked for
    again for their tracklist."""
    linked = {album.release_id for album in albums if album.release_id is not None}
    new = linked - releases.keys()
    without_tracks = {
        i
        for i in linked & releases.keys()
        if releases[i].tracklist is None or any(track.writers is None for track in releases[i].tracklist)
    }
    return new, without_tracks


def enrich_collection(
    store: JsonStore,
    client: DiscogsClient,
    progress: Callable[[int, int], None] = lambda done, total: None,
    part: Callable[[str, int, int], None] = lambda name, done, total: None,
) -> int:
    """Fetch what the Discogs cache still lacks for the stored albums and artists, then apply it.

    Returns the number of lookups made. The cache is saved along the way, so an
    interrupted run picks up where it stopped. Progress counts the lookups of
    this run; part names what is being fetched ("albums", then "pictures") and
    how many of all of them are in, earlier runs included.
    """
    albums = store.load(Album)
    releases = {release.release_id: release for release in store.load(ReleaseEnrichment)}
    masters = {master.master_id: master for master in store.load(MasterEnrichment)}
    pictures = {artist.discogs_artist_id: artist for artist in store.load(ArtistEnrichment)}
    new_ids, tracklist_ids = releases_to_fetch(albums, releases)
    release_ids = sorted(new_ids | tracklist_ids)
    artist_ids = sorted(
        discogs_id
        for discogs_id in {
            a.discogs_artist_id for a in store.load(Artist) if a.discogs_artist_id is not None
        }
        # A record from before membership was kept is fetched again, once.
        if discogs_id not in pictures or pictures[discogs_id].member_ids is None
    )
    # Each new release may bring one master lookup with it.
    done, saved, total = 0, 0, 2 * len(new_ids) + len(tracklist_ids) + len(artist_ids)
    linked_count = len({a.release_id for a in albums if a.release_id is not None})
    named_count = len(
        {a.discogs_artist_id for a in store.load(Artist) if a.discogs_artist_id is not None}
    )
    part("pictures", named_count - len(artist_ids), named_count)
    part("albums", linked_count - len(release_ids), linked_count)
    try:
        for count, release_id in enumerate(release_ids, start=1):
            release = client.release(release_id)
            # Fetched now, so asked for with its tracklist and writers: none is an empty one,
            # never asked for again.
            release = replace(
                release,
                tracklist=tuple(replace(track, writers=track.writers or ()) for track in release.tracklist or ()),
            )
            done += 1
            if release_id in tracklist_ids:
                # Fetched before for its styles and year: only the tracklist is new. What the
                # sorting goes by is left as it was, so nothing moves because of this.
                releases[release_id] = replace(releases[release_id], tracklist=release.tracklist)
            else:
                releases[release_id] = release
                if release.master_id is None or release.master_id in masters:
                    total -= 1
                else:
                    masters[release.master_id] = client.master(release.master_id)
                    done += 1
            part("albums", linked_count - len(release_ids) + count, linked_count)
            progress(done, total)
            if done - saved >= SAVE_CACHE_EVERY:
                _save_cache(store, releases, masters, pictures)
                saved = done
        # Masters of releases cached by a run that stopped between the two lookups.
        for release in list(releases.values()):
            if release.master_id is not None and release.master_id not in masters:
                masters[release.master_id] = client.master(release.master_id)
                done += 1
                total += 1
                progress(done, total)
        # Last, as nothing in the sorting waits for them: the pictures of the artists.
        for count, artist_id in enumerate(artist_ids, start=1):
            pictures[artist_id] = client.artist(artist_id)
            done += 1
            part("pictures", named_count - len(artist_ids) + count, named_count)
            progress(done, total)
            if done - saved >= SAVE_CACHE_EVERY:
                _save_cache(store, releases, masters, pictures)
                saved = done
    finally:
        _save_cache(store, releases, masters, pictures)
    apply_enrichment(store)
    # Last of all: the images themselves, so the pages show them without Discogs.
    urls = missing_images(store, albums, pictures.values())
    total += len(urls)
    stored = len(image_urls(albums, pictures.values())) - len(urls)
    part("covers", stored, stored + len(urls))

    def image_progress(count: int) -> None:
        part("covers", stored + count, stored + len(urls))
        progress(done + count, total)

    download_images(store, client, urls, image_progress)
    return done + len(urls)


def _save_cache(store: JsonStore, releases: dict, masters: dict, pictures: dict) -> None:
    store.save(ReleaseEnrichment, releases.values())
    store.save(MasterEnrichment, masters.values())
    store.save(ArtistEnrichment, pictures.values())


def apply_enrichment(store: JsonStore) -> None:
    """Carry the cached Discogs data over to the albums: master, original year and styles."""
    albums = store.load(Album)
    releases = {release.release_id: release for release in store.load(ReleaseEnrichment)}
    masters = {master.master_id: master for master in store.load(MasterEnrichment)}
    clusters = store.load(Cluster)
    styles = {style.name: style for style in store.load(Style)}
    artist_cluster = {
        assignment.artist_id: assignment.cluster_id
        for assignment in store.load(ArtistClusterAssignment)
        if assignment.cluster_id is not None
    }

    album_styles: dict[int, tuple[str, ...]] = {}
    for album in albums:
        release = releases.get(album.release_id)
        if release is None:
            continue
        album.master_id = release.master_id
        album_styles[album.id] = release.styles
        if not album.original_year_confirmed:
            master = masters.get(release.master_id)
            # Without a master this release is the only version, so its year is the original.
            year = master.original_release_year if master else release.year
            if release.master_id is None or master is not None:
                album.original_release_year = year or album.original_release_year

    # A style seen for the first time joins the cluster most of its albums' artists are
    # already in; with no such cluster it gets one of its own, named after it.
    votes: dict[str, Counter[int]] = defaultdict(Counter)
    for album in albums:
        for name in album_styles.get(album.id, ()):
            if name not in styles and album.artist_id in artist_cluster:
                votes[name][artist_cluster[album.artist_id]] += 1
    cluster_ids = {cluster.name: cluster.id for cluster in clusters}
    for name in sorted({name for names in album_styles.values() for name in names}):
        if name in styles:
            continue
        if votes[name]:
            cluster_id = votes[name].most_common(1)[0][0]
        else:
            cluster_id = cluster_ids.get(name)
            if cluster_id is None:
                cluster_id = store.next_id(Cluster, clusters)
                clusters.append(Cluster(cluster_id, name))
                cluster_ids[name] = cluster_id
        styles[name] = Style(store.next_id(Style, styles.values()), name, cluster_id)

    for album in albums:
        if album.id in album_styles:
            album.style_ids = [styles[name].id for name in album_styles[album.id]]

    store.save(Cluster, clusters)
    store.save(Style, styles.values())
    store.save(Album, albums)
    ensure_cluster_order(store)
