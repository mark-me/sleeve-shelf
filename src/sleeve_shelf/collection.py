"""Application services for the collection as a whole: loading a layout, or starting empty."""

from collections import defaultdict
from dataclasses import replace

from sleeve_shelf.domain import (
    Album,
    AliasGroup,
    Artist,
    ArtistClusterAssignment,
    Cabinet,
    Cluster,
    EraBand,
    EraBandSource,
    FamilyDismissal,
    UnrelatedArtists,
    MatchProposal,
    Placement,
    Shelf,
    Style,
    WidthConstants,
    settle_order,
)
from sleeve_shelf.ingestion.initial_load import InitialLoad
from sleeve_shelf.persistence import BrowseQueries, JsonStore
from sleeve_shelf.sorting.order import cluster_order_from_layout
from sleeve_shelf.versions import save_if_unsaved, save_version
from sleeve_shelf.widths import estimate_widths


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
    store.save(UnrelatedArtists, [])
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
        candidates[album_key(artist_names[album.artist_id], album.title)].append(album)
    artist_ids = {artist.name: artist.id for artist in artists}
    cluster_ids = {cluster.name: cluster.id for cluster in clusters}
    band_ids = {(band.artist_id, band.label): band.id for band in era_bands}

    def stored(loaded: Album) -> Album:
        """The stored album a workbook row stands for, added when it is new."""
        artist = loaded_artist[loaded.artist_id]
        matches = candidates[album_key(artist.name, loaded.title)]
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


def album_key(artist: str, title: str) -> tuple[str, str]:
    """Artist and title as albums are recognised by: case and spacing do not count."""
    return " ".join(artist.casefold().split()), " ".join(title.casefold().split())
