"""Application services that tie ingestion to persistence."""

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher

from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    Cabinet,
    Cluster,
    EraBand,
    MasterEnrichment,
    MatchProposal,
    Placement,
    ReleaseEnrichment,
    Shelf,
    Style,
    WidthConstants,
)
from sleeve_shelf.ingestion.discogs_api import DiscogsClient
from sleeve_shelf.ingestion.discogs_csv import CollectionItem
from sleeve_shelf.ingestion.initial_load import InitialLoad
from sleeve_shelf.persistence import JsonStore

# Below this similarity a loaded album and a Discogs release are not even proposed as a match.
PROPOSAL_THRESHOLD = 0.6
SAVE_CACHE_EVERY = 25


def replace_collection(
    store: JsonStore, load: InitialLoad, constants: WidthConstants | None = None
) -> None:
    """Replace everything stored with an initial load, and save it as the first version."""
    if constants:
        estimate_widths(load.albums, constants)
    store.save(Cabinet, load.cabinets)
    store.save(Shelf, load.shelves)
    store.save(Cluster, load.clusters)
    store.save(Artist, load.artists)
    store.save(ArtistClusterAssignment, load.assignments)
    store.save(EraBand, load.era_bands)
    store.save(Album, load.albums)
    store.save(Placement, load.placements)
    # Styles and proposed matches belong to the albums that were just replaced;
    # the Discogs cache is kept, so nothing has to be fetched twice.
    store.save(Style, [])
    store.save(MatchProposal, [])
    # Earlier versions point at albums that no longer exist.
    store.clear_snapshots()
    store.save_snapshot(datetime.now().strftime("%Y%m%d-%H%M%S"))


def estimate_widths(albums: list[Album], constants: WidthConstants) -> None:
    """Compute each album's width from its format; compound formats await a manual width."""
    for album in albums:
        if album.format_tokens is None:
            continue
        album.computed_width_cm = round(album.format_tokens.estimated_width_cm(constants), 2)
        album.width_confirmed = (
            not album.format_tokens.is_compound or album.manual_width_cm is not None
        )


@dataclass(frozen=True, slots=True)
class ImportResult:
    """What importing a Discogs export did to the collection."""

    vinyl_count: int
    skipped_non_vinyl: int
    matched: int
    proposed: int
    added: int
    unmatched_albums: int


def import_discogs_collection(
    store: JsonStore, items: list[CollectionItem], constants: WidthConstants
) -> ImportResult:
    """Link the stored albums to the releases of a Discogs export, and add what is new.

    Albums and releases with the same artist and title are linked outright. For
    what is left, a similar-looking release is only proposed, to be confirmed by
    hand. Vinyl releases that no album accounts for become new, unplaced albums.
    """
    albums = store.load(Album)
    artists = store.load(Artist)
    artist_names = {artist.id: artist.name for artist in artists}
    vinyl = [item for item in items if item.is_vinyl]

    known_releases = {album.release_id for album in albums if album.release_id is not None}
    available = [item for item in vinyl if item.release_id not in known_releases]
    by_key: dict[tuple[str, str], list[CollectionItem]] = defaultdict(list)
    for item in available:
        by_key[_key(item.artist, item.title)].append(item)

    matched = 0
    unmatched: list[Album] = []
    for album in albums:
        if album.release_id is not None:
            continue
        candidates = by_key[_key(artist_names[album.artist_id], album.title)]
        if not candidates:
            unmatched.append(album)
            continue
        # Two pressings of one title are told apart by their format.
        qualifiers = album.format_tokens.qualifiers if album.format_tokens else None
        item = next(
            (c for c in candidates if c.format_tokens.qualifiers == qualifiers), candidates[0]
        )
        candidates.remove(item)
        album.release_id = item.release_id
        if album.format_tokens is None:
            album.format_tokens = item.format_tokens
        matched += 1

    remaining = [item for candidates in by_key.values() for item in candidates]
    proposals: list[MatchProposal] = []
    for album in unmatched:
        text = f"{artist_names[album.artist_id]} {album.title}".casefold()
        scored = [
            (SequenceMatcher(None, text, f"{item.artist} {item.title}".casefold()).ratio(), item)
            for item in remaining
        ]
        score, item = max(scored, key=lambda pair: pair[0], default=(0.0, None))
        if item is not None and score >= PROPOSAL_THRESHOLD:
            remaining.remove(item)
            proposals.append(
                MatchProposal(album.id, item.release_id, item.artist, item.title, round(score, 3))
            )

    artist_ids = {artist.name: artist.id for artist in artists}
    for item in remaining:
        artist_id = artist_ids.get(item.artist)
        if artist_id is None:
            artist_id = max((artist.id for artist in artists), default=0) + 1
            artists.append(Artist(artist_id, item.artist))
            artist_ids[item.artist] = artist_id
        albums.append(
            Album(
                id=max((album.id for album in albums), default=0) + 1,
                artist_id=artist_id,
                title=item.title,
                release_id=item.release_id,
                format_tokens=item.format_tokens,
            )
        )

    estimate_widths(albums, constants)
    store.save(Artist, artists)
    store.save(Album, albums)
    store.save(MatchProposal, proposals)
    return ImportResult(
        vinyl_count=len(vinyl),
        skipped_non_vinyl=len(items) - len(vinyl),
        matched=matched,
        proposed=len(proposals),
        added=len(remaining),
        unmatched_albums=len(unmatched) - len(proposals),
    )


def _key(artist: str, title: str) -> tuple[str, str]:
    return " ".join(artist.casefold().split()), " ".join(title.casefold().split())


def enrich_collection(
    store: JsonStore,
    client: DiscogsClient,
    progress: Callable[[int, int], None] = lambda done, total: None,
) -> int:
    """Fetch what the Discogs cache still lacks for the stored albums, then apply it.

    Returns the number of lookups made. The cache is saved along the way, so an
    interrupted run picks up where it stopped.
    """
    albums = store.load(Album)
    releases = {release.release_id: release for release in store.load(ReleaseEnrichment)}
    masters = {master.master_id: master for master in store.load(MasterEnrichment)}
    release_ids = sorted(
        {a.release_id for a in albums if a.release_id is not None} - releases.keys()
    )
    # Each new release may bring one master lookup with it.
    done, saved, total = 0, 0, 2 * len(release_ids)
    try:
        for release_id in release_ids:
            release = client.release(release_id)
            releases[release_id] = release
            done += 1
            if release.master_id is None or release.master_id in masters:
                total -= 1
            else:
                masters[release.master_id] = client.master(release.master_id)
                done += 1
            progress(done, total)
            if done - saved >= SAVE_CACHE_EVERY:
                _save_cache(store, releases, masters)
                saved = done
        # Masters of releases cached by a run that stopped between the two lookups.
        for release in list(releases.values()):
            if release.master_id is not None and release.master_id not in masters:
                masters[release.master_id] = client.master(release.master_id)
                done += 1
                total += 1
                progress(done, total)
    finally:
        _save_cache(store, releases, masters)
    apply_enrichment(store)
    return done


def _save_cache(store: JsonStore, releases: dict, masters: dict) -> None:
    store.save(ReleaseEnrichment, releases.values())
    store.save(MasterEnrichment, masters.values())


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
                cluster_id = max((cluster.id for cluster in clusters), default=0) + 1
                clusters.append(Cluster(cluster_id, name))
                cluster_ids[name] = cluster_id
        styles[name] = Style(len(styles) + 1, name, cluster_id)

    for album in albums:
        if album.id in album_styles:
            album.style_ids = [styles[name].id for name in album_styles[album.id]]

    store.save(Cluster, clusters)
    store.save(Style, styles.values())
    store.save(Album, albums)
