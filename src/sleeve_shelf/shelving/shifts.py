"""Application service for cluster shifts: a new purchase that points an artist elsewhere."""

from collections import defaultdict
from dataclasses import dataclass

from sleeve_shelf.domain import Album, ArtistClusterAssignment, Style
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.sorting.order import propose_cluster


@dataclass(frozen=True, slots=True)
class ClusterShift:
    """An artist with a confirmed cluster whose new purchases make the styles point to another."""

    artist_id: int
    cluster_id: int
    proposed_cluster_id: int
    # The purchases behind it: the new albums that have their styles.
    album_ids: tuple[int, ...]


def cluster_shifts(store: JsonStore) -> list[ClusterShift]:
    """The shifts waiting for a decision; nothing is ever moved to another cluster by itself.

    Only a purchase can cause one: the cluster the styles point to with the new
    albums is compared with the one they pointed to without them, so an artist
    whose curated cluster never agreed with its styles is not reported.
    """
    albums = store.load(Album)
    if not any(album.new_purchase for album in albums):
        return []
    styles = {style.id: style for style in store.load(Style)}
    confirmed = {
        a.artist_id: a.cluster_id for a in store.load(ArtistClusterAssignment) if a.confirmed
    }
    by_artist: dict[int, list[Album]] = defaultdict(list)
    for album in albums:
        # Singles and EPs are kept outside the layout and have no say in the cluster.
        if album.format_tokens is None or album.format_tokens.is_lp:
            by_artist[album.artist_id].append(album)

    shifts = []
    for artist_id, cluster_id in confirmed.items():
        purchases = [a for a in by_artist[artist_id] if a.new_purchase and a.style_ids]
        if not purchases:
            continue
        before = propose_cluster([a for a in by_artist[artist_id] if not a.new_purchase], styles)
        after = propose_cluster(by_artist[artist_id], styles)
        if after is not None and after != cluster_id and after != before:
            shifts.append(
                ClusterShift(artist_id, cluster_id, after, tuple(a.id for a in purchases))
            )
    return shifts


def keep_cluster(store: JsonStore, artist_id: int) -> None:
    """The artist stays where it is: its purchases have been weighed and are not asked about again."""
    clear_purchases(store, artist_id)


def clear_purchases(store: JsonStore, artist_id: int) -> None:
    """Forget which albums of the artist are new purchases; a decision on its cluster was taken."""
    albums = store.load(Album)
    marked = [a for a in albums if a.artist_id == artist_id and a.new_purchase]
    if not marked:
        return
    for album in marked:
        album.new_purchase = False
    store.save(Album, albums)
