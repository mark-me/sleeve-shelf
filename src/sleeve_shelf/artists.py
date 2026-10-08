"""Application services for curating an artist: start year and cluster."""

from sleeve_shelf.collection import ensure_cluster_order
from sleeve_shelf.domain import Artist, ArtistClusterAssignment, Cluster
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
            existing = Cluster(max((c.id for c in clusters), default=0) + 1, new_cluster_name)
            clusters.append(existing)
            store.save(Cluster, clusters)
            ensure_cluster_order(store)
        cluster_id = existing.id
    if cluster_id is not None:
        assignments.append(ArtistClusterAssignment(artist_id, cluster_id, confirmed=True))
    store.save(ArtistClusterAssignment, assignments)


def confirm_cluster(store: JsonStore, artist_id: int) -> None:
    """Confirm the cluster that was proposed for the artist."""
    assignments = store.load(ArtistClusterAssignment)
    for assignment in assignments:
        if assignment.artist_id == artist_id:
            assignment.confirmed = True
    store.save(ArtistClusterAssignment, assignments)
