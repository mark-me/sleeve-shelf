"""Application services that tie ingestion to persistence."""

from datetime import datetime

from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    Cabinet,
    Cluster,
    EraBand,
    Placement,
    Shelf,
)
from sleeve_shelf.ingestion.initial_load import InitialLoad
from sleeve_shelf.persistence import JsonStore


def replace_collection(store: JsonStore, load: InitialLoad) -> None:
    """Replace everything stored with an initial load, and save it as the first version."""
    store.save(Cabinet, load.cabinets)
    store.save(Shelf, load.shelves)
    store.save(Cluster, load.clusters)
    store.save(Artist, load.artists)
    store.save(ArtistClusterAssignment, load.assignments)
    store.save(EraBand, load.era_bands)
    store.save(Album, load.albums)
    store.save(Placement, load.placements)
    # Earlier versions point at albums that no longer exist.
    store.clear_snapshots()
    store.save_snapshot(datetime.now().strftime("%Y%m%d-%H%M%S"))
