"""Application services that tie ingestion to persistence."""

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from difflib import SequenceMatcher

from sleeve_shelf.domain import (
    Album,
    AliasGroup,
    Artist,
    ArtistClusterAssignment,
    ArtistEnrichment,
    Cabinet,
    Cluster,
    EraBand,
    EraBandSource,
    FamilyDismissal,
    LocationRule,
    LocationRuleTarget,
    MasterEnrichment,
    MatchProposal,
    Placement,
    ProposedPlacement,
    ReleaseEnrichment,
    Shelf,
    Style,
    WidthConstants,
    settle_order,
)
from sleeve_shelf.ingestion.discogs_api import DiscogsClient
from sleeve_shelf.ingestion.discogs_csv import CollectionItem
from sleeve_shelf.ingestion.initial_load import InitialLoad
from sleeve_shelf.persistence import BrowseQueries, JsonStore
from sleeve_shelf.sorting.order import cluster_order_from_layout
from sleeve_shelf.versions import save_if_unsaved, save_version

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
    # Styles, proposed matches and families belong to the albums and artists that
    # were just replaced; the Discogs cache is kept, so nothing has to be fetched twice.
    store.save(Style, [])
    store.save(MatchProposal, [])
    store.save(AliasGroup, [])
    store.save(FamilyDismissal, [])
    ensure_cluster_order(store)
    # Earlier versions point at albums that no longer exist.
    store.clear_snapshots()
    save_version(store, "loaded")


def load_layout(
    store: JsonStore, load: InitialLoad, constants: WidthConstants | None = None
) -> None:
    """Take in a layout workbook: the first time everything, after that only the layout."""
    if store.exists(Album):
        update_layout(store, load, constants)
    else:
        replace_collection(store, load, constants)


def update_layout(
    store: JsonStore, load: InitialLoad, constants: WidthConstants | None = None
) -> None:
    """Apply a newly loaded workbook to the stored collection as a change of layout only.

    Albums are recognised by artist and title and keep everything known about
    them — Discogs link, years, styles, family, cluster. Where they stand is
    taken from the workbook. Albums the workbook doesn't list become unplaced;
    albums, cabinets and shelves that are new are added.
    """
    artists = store.load(Artist)
    albums = store.load(Album)
    clusters = store.load(Cluster)
    assignments = store.load(ArtistClusterAssignment)
    era_bands = store.load(EraBand)
    cabinets = store.load(Cabinet)
    shelves = store.load(Shelf)
    # Changes made by hand since the last version must not be lost to the new workbook.
    save_if_unsaved(store, "before loading")

    loaded_artist = {artist.id: artist for artist in load.artists}
    loaded_cluster = {cluster.id: cluster.name for cluster in load.clusters}
    loaded_assignment = {a.artist_id: a.cluster_id for a in load.assignments}
    loaded_band = {band.id: band for band in load.era_bands}
    loaded_cabinet = {cabinet.id: cabinet for cabinet in load.cabinets}

    # Cabinets and shelves are recognised by name and keep what was filled in for them.
    cabinet_ids = {cabinet.name: cabinet.id for cabinet in cabinets}
    shelf_ids = {(shelf.cabinet_id, shelf.name): shelf.id for shelf in shelves}
    shelf_of: dict[int, int] = {}
    for shelf in load.shelves:
        cabinet_name = loaded_cabinet[shelf.cabinet_id].name
        if cabinet_name not in cabinet_ids:
            cabinet_ids[cabinet_name] = store.next_id(Cabinet, cabinets)
            cabinets.append(Cabinet(cabinet_ids[cabinet_name], cabinet_name))
        key = (cabinet_ids[cabinet_name], shelf.name)
        if key not in shelf_ids:
            shelf_ids[key] = store.next_id(Shelf, shelves)
            shelves.append(
                Shelf(
                    shelf_ids[key],
                    key[0],
                    shelf.name,
                    width_cm=shelf.width_cm,
                    reachability_score=shelf.reachability_score,
                )
            )
        shelf_of[shelf.id] = shelf_ids[key]

    artist_names = {artist.id: artist.name for artist in artists}
    candidates: dict[tuple[str, str], list[Album]] = defaultdict(list)
    for album in albums:
        candidates[_key(artist_names[album.artist_id], album.title)].append(album)
    artist_ids = {artist.name: artist.id for artist in artists}
    cluster_ids = {cluster.name: cluster.id for cluster in clusters}
    band_ids = {(band.artist_id, band.label): band.id for band in era_bands}

    def stored(loaded: Album) -> Album:
        """The stored album a workbook row stands for, added when it is new."""
        artist = loaded_artist[loaded.artist_id]
        matches = candidates[_key(artist.name, loaded.title)]
        if matches:
            qualifiers = loaded.format_tokens.qualifiers if loaded.format_tokens else None
            album = next(
                (m for m in matches if m.format_tokens and m.format_tokens.qualifiers == qualifiers),
                matches[0],
            )
            matches.remove(album)
            return album
        if artist.name not in artist_ids:
            artist_ids[artist.name] = store.next_id(Artist, artists)
            artists.append(Artist(artist_ids[artist.name], artist.name, start_year=artist.start_year))
            cluster_name = loaded_cluster.get(loaded_assignment.get(artist.id))
            if cluster_name is not None:
                if cluster_name not in cluster_ids:
                    cluster_ids[cluster_name] = store.next_id(Cluster, clusters)
                    clusters.append(Cluster(cluster_ids[cluster_name], cluster_name))
                assignments.append(
                    ArtistClusterAssignment(artist_ids[artist.name], cluster_ids[cluster_name], True)
                )
        artist_id = artist_ids[artist.name]
        era_band_id = None
        if loaded.era_band_id is not None:
            label = loaded_band[loaded.era_band_id].label
            if (artist_id, label) not in band_ids:
                band_ids[artist_id, label] = max((b.id for b in era_bands), default=0) + 1
                position = sum(1 for band in era_bands if band.artist_id == artist_id)
                era_bands.append(
                    EraBand(band_ids[artist_id, label], artist_id, label, position, EraBandSource.INITIAL_LOAD)
                )
            era_band_id = band_ids[artist_id, label]
        album = replace(
            loaded,
            id=store.next_id(Album, albums),
            artist_id=artist_id,
            era_band_id=era_band_id,
        )
        albums.append(album)
        return album

    placement_of = {placement.album_id: placement for placement in load.placements}
    placements = []
    for loaded in load.albums:
        album = stored(loaded)
        placement = placement_of.get(loaded.id)
        if placement is not None:
            placements.append(replace(placement, album_id=album.id, shelf_id=shelf_of[placement.shelf_id]))

    if constants:
        estimate_widths([album for album in albums if album.computed_width_cm is None], constants)
    # New cabinets and shelves come after the ones already there.
    settle_order(cabinets, shelves)
    store.save(Cabinet, cabinets)
    store.save(Shelf, shelves)
    store.save(Cluster, clusters)
    store.save(Artist, artists)
    store.save(ArtistClusterAssignment, assignments)
    store.save(EraBand, era_bands)
    store.save(Album, albums)
    store.save(Placement, placements)
    ensure_cluster_order(store)
    save_version(store, "loaded")


def start_empty(store: JsonStore) -> None:
    """Begin a collection without a layout workbook: nothing in it yet, to be filled from Discogs."""
    if not store.exists(Album):
        store.save(Album, [])


def ensure_cluster_order(store: JsonStore) -> None:
    """Give every cluster a position in the sequence of clusters.

    The sequence is read off the current layout once; a cluster that has no
    position yet after that (it is new, or holds no placed album) goes to the end.
    """
    clusters = store.load(Cluster)
    if all(cluster.position is not None for cluster in clusters):
        return
    has_layout = all(
        store.exists(entity)
        for entity in (Album, Artist, ArtistClusterAssignment, EraBand, Placement, Shelf, Cabinet)
    )
    if has_layout and all(cluster.position is None for cluster in clusters):
        cluster_of = {
            assignment.artist_id: assignment.cluster_id
            for assignment in store.load(ArtistClusterAssignment)
        }
        artist_of = {album.id: album.artist_id for album in store.load(Album)}
        queries = BrowseQueries(store)
        layout = [
            cluster_of.get(artist_of[row.album_id])
            for shelf in queries.shelves()
            for row in queries.shelf_albums(shelf.shelf_id)
        ]
        by_id = {cluster.id: cluster for cluster in clusters}
        for position, cluster_id in enumerate(cluster_order_from_layout(layout)):
            if cluster_id in by_id:
                by_id[cluster_id].position = position
    following = max((c.position for c in clusters if c.position is not None), default=-1) + 1
    for cluster in sorted(clusters, key=lambda cluster: cluster.id):
        if cluster.position is None:
            cluster.position = following
            following += 1
    store.save(Cluster, clusters)


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
    # Artist and title of the albums whose release is no longer in the Discogs collection.
    gone: tuple[tuple[str, str], ...] = ()
    # Linked albums whose format was brought up to date.
    refreshed: int = 0


def import_discogs_collection(
    store: JsonStore,
    items: list[CollectionItem],
    constants: WidthConstants,
    dry_run: bool = False,
    refresh_formats: bool = False,
) -> ImportResult:
    """Link the stored albums to the releases of a Discogs export, and add what is new.

    Albums and releases with the same artist and title are linked outright. For
    what is left, a similar-looking release is only proposed, to be confirmed by
    hand. Vinyl releases that no album accounts for become new, unplaced albums.
    Albums whose release the collection no longer holds are marked and reported,
    never removed. With refresh_formats the albums that are already linked take
    the format of their release — for a sync, which knows the format better than
    an export does. A dry run only reports what would happen.
    """
    albums = store.load(Album)
    artists = store.load(Artist)
    artist_names = {artist.id: artist.name for artist in artists}
    vinyl = [item for item in items if item.is_vinyl]

    known_releases = {album.release_id for album in albums if album.release_id is not None}
    in_collection = {item.release_id for item in items}
    gone = []
    for album in albums:
        album.left_discogs = (
            album.release_id is not None and album.release_id not in in_collection
        )
        if album.left_discogs:
            gone.append((artist_names[album.artist_id], album.title))

    # A cover only comes with a sync; an export leaves the covers as they are.
    covers = {item.release_id: item.cover_url for item in vinyl if item.cover_url}
    large_covers = {
        item.release_id: item.cover_image_url for item in vinyl if item.cover_image_url
    }

    refreshed = 0
    if refresh_formats:
        formats = {item.release_id: item.format_tokens for item in vinyl}
        for album in albums:
            current = formats.get(album.release_id)
            if current is not None and album.format_tokens != current:
                album.format_tokens = current
                refreshed += 1
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
                MatchProposal(
                    album.id,
                    item.release_id,
                    item.artist,
                    item.title,
                    round(score, 3),
                    item.format_tokens,
                )
            )

    artist_ids = {artist.name: artist.id for artist in artists}
    for item in remaining:
        artist_id = artist_ids.get(item.artist)
        if artist_id is None:
            artist_id = store.next_id(Artist, artists)
            artists.append(Artist(artist_id, item.artist))
            artist_ids[item.artist] = artist_id
        albums.append(
            Album(
                id=store.next_id(Album, albums),
                artist_id=artist_id,
                title=item.title,
                release_id=item.release_id,
                format_tokens=item.format_tokens,
            )
        )

    for album in albums:
        if album.release_id in covers:
            album.cover_url = covers[album.release_id]
        if album.release_id in large_covers:
            album.cover_image_url = large_covers[album.release_id]

    # Only a sync names the artist on Discogs. An artist is the one most of its releases
    # are credited to; releases shared with other artists say nothing.
    credited = {item.release_id: item.artist_discogs_id for item in vinyl if item.artist_discogs_id}
    votes: dict[int, Counter] = defaultdict(Counter)
    for album in albums:
        if album.release_id in credited:
            votes[album.artist_id][credited[album.release_id]] += 1
    for artist in artists:
        if artist.id in votes:
            artist.discogs_artist_id = votes[artist.id].most_common(1)[0][0]

    if not dry_run:
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
        gone=tuple(gone),
        refreshed=refreshed,
    )


def confirm_match(store: JsonStore, album_id: int, constants: WidthConstants) -> None:
    """Accept a proposed match: the album takes the proposed release."""
    proposals = store.load(MatchProposal)
    proposal = next((p for p in proposals if p.album_id == album_id), None)
    if proposal is None:
        return
    albums = store.load(Album)
    album = next(album for album in albums if album.id == album_id)
    album.release_id = proposal.release_id
    if album.format_tokens is None:
        album.format_tokens = proposal.format_tokens
    estimate_widths([album], constants)
    store.save(Album, albums)
    store.save(MatchProposal, [p for p in proposals if p is not proposal])


def reject_match(store: JsonStore, album_id: int, constants: WidthConstants) -> None:
    """Turn a proposed match down: the release becomes a new, unplaced album of its own."""
    proposals = store.load(MatchProposal)
    proposal = next((p for p in proposals if p.album_id == album_id), None)
    if proposal is None:
        return
    albums = store.load(Album)
    artists = store.load(Artist)
    artist = next((artist for artist in artists if artist.name == proposal.artist), None)
    if artist is None:
        artist = Artist(store.next_id(Artist, artists), proposal.artist)
        artists.append(artist)
    album = Album(
        id=store.next_id(Album, albums),
        artist_id=artist.id,
        title=proposal.title,
        release_id=proposal.release_id,
        format_tokens=proposal.format_tokens,
    )
    estimate_widths([album], constants)
    albums.append(album)
    store.save(Artist, artists)
    store.save(Album, albums)
    store.save(MatchProposal, [p for p in proposals if p is not proposal])


def remove_departed_album(store: JsonStore, album_id: int) -> bool:
    """Remove an album whose release left the Discogs collection; the caller has asked first.

    The album goes, with its place on a shelf (also in a waiting proposal), its
    own location rule and a proposed match. The layout is saved as a version
    before an album is taken off its shelf. The artist stays, even without albums.
    Any other album is left alone: only one marked as gone can be removed here.
    """
    albums = store.load(Album)
    album = next((a for a in albums if a.id == album_id and a.left_discogs), None)
    if album is None:
        return False

    def is_other(placement: Placement) -> bool:
        return placement.album_id != album_id

    placements = store.load(Placement)
    if not all(is_other(placement) for placement in placements):
        save_if_unsaved(store, "before removing an album")
        store.save(Placement, [p for p in placements if is_other(p)])
    if store.exists(ProposedPlacement):
        store.save(ProposedPlacement, [p for p in store.load(ProposedPlacement) if is_other(p)])
    rules = store.load(LocationRule)
    kept_rules = [
        rule
        for rule in rules
        if rule.target_type is not LocationRuleTarget.ALBUM or rule.target_id != album_id
    ]
    if len(kept_rules) != len(rules):
        store.save(LocationRule, kept_rules)
    proposals = store.load(MatchProposal)
    if any(proposal.album_id == album_id for proposal in proposals):
        store.save(MatchProposal, [p for p in proposals if p.album_id != album_id])
    store.save(Album, [a for a in albums if a.id != album_id])
    return True


def _key(artist: str, title: str) -> tuple[str, str]:
    return " ".join(artist.casefold().split()), " ".join(title.casefold().split())


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
    release_ids = sorted(
        {a.release_id for a in albums if a.release_id is not None} - releases.keys()
    )
    artist_ids = sorted(
        {a.discogs_artist_id for a in store.load(Artist) if a.discogs_artist_id is not None}
        - pictures.keys()
    )
    # Each new release may bring one master lookup with it.
    done, saved, total = 0, 0, 2 * len(release_ids) + len(artist_ids)
    linked_count = len(release_ids) + len(
        {a.release_id for a in albums if a.release_id is not None} & releases.keys()
    )
    named_count = len(artist_ids) + len(pictures)
    part("pictures", named_count - len(artist_ids), named_count)
    part("albums", linked_count - len(release_ids), linked_count)
    try:
        for count, release_id in enumerate(release_ids, start=1):
            release = client.release(release_id)
            releases[release_id] = release
            done += 1
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
    return done


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
