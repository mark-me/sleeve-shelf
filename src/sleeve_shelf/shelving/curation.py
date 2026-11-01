"""What curating an artist takes.

The list of artists with what each still needs, and all that the page of one artist shows besides
its figures.
"""

from collections import defaultdict

from sleeve_shelf.domain import (
    Album,
    AliasGroup,
    Artist,
    ArtistClusterAssignment,
    ArtistEnrichment,
    Cluster,
    Style,
    clusters_in_order,
    find_by_id,
    sort_name,
)
from sleeve_shelf.library.alias_groups import cluster_hints
from sleeve_shelf.library.artists import albums_per_artist
from sleeve_shelf.library.taking_part import albums_taking_part
from sleeve_shelf.persistence import BrowseQueries, JsonStore
from sleeve_shelf.shelving.places import described_rules
from sleeve_shelf.shelving.shifts import ClusterShift, cluster_shifts
from sleeve_shelf.sorting.connections import connections_of
from sleeve_shelf.sorting.eras import band_of
from sleeve_shelf.sorting.order import propose_cluster


def _albums_by_artist(store: JsonStore) -> dict[int, list[Album]]:
    by_artist: dict[int, list[Album]] = defaultdict(list)
    for album in albums_taking_part(store):
        by_artist[album.artist_id].append(album)
    return by_artist


def _earliest_year(albums: list[Album]) -> int | None:
    return min((a.original_release_year for a in albums if a.original_release_year), default=None)


def _needs_attention(
    artist: Artist,
    assignment: ArtistClusterAssignment | None,
    sorted_albums: list[Album],
    shift: ClusterShift | None,
) -> bool:
    """Only artists that are sorted need a cluster and a start year; a shift waits for a decision."""
    return shift is not None or bool(sorted_albums) and (
        assignment is None or not assignment.confirmed or artist.start_year is None
    )


def artist_rows(store: JsonStore) -> list[dict]:
    """Every artist with what the list says about it, by name.

    Args:
        store: The store of the collection.

    Returns:
        One row per artist, for the list's template.
    """
    by_artist = _albums_by_artist(store)
    album_counts = albums_per_artist(store)
    cluster_names = {cluster.id: cluster.name for cluster in store.load(Cluster)}
    assignments = {a.artist_id: a for a in store.load(ArtistClusterAssignment)}
    families = {group.id: group.label for group in store.load(AliasGroup)}
    shifts = {shift.artist_id: shift for shift in cluster_shifts(store)}
    rows = []
    for artist in store.load(Artist):
        assignment = assignments.get(artist.id)
        sorted_albums = by_artist.get(artist.id, [])
        shift = shifts.get(artist.id)
        rows.append(
            {
                "artist": artist,
                "albums": album_counts[artist.id],
                "cluster_id": assignment.cluster_id if assignment else None,
                "cluster": cluster_names.get(assignment.cluster_id) if assignment else None,
                "cluster_confirmed": bool(assignment and assignment.confirmed),
                "derived_year": _earliest_year(sorted_albums),
                "family": families.get(artist.alias_group_id),
                "attention": _needs_attention(artist, assignment, sorted_albums, shift),
                "shift_to": cluster_names.get(shift.proposed_cluster_id) if shift else None,
                "sorted": bool(sorted_albums),
            }
        )
    return sorted(rows, key=lambda row: sort_name(row["artist"].name))


def artist_details(store: JsonStore, artist: Artist) -> dict:
    """What the page of one artist shows about its cluster, connections, family and albums.

    Args:
        store: The store of the collection.
        artist: The artist.

    Returns:
        What the page's template uses, by name, and needs_attention for the view.
    """
    artist_id = artist.id
    albums = [album for album in store.load(Album) if album.artist_id == artist_id]
    sorted_albums = _albums_by_artist(store).get(artist_id, [])
    clusters = clusters_in_order(store.load(Cluster))
    cluster_names = {cluster.id: cluster.name for cluster in clusters}
    assignments = store.load(ArtistClusterAssignment)
    assignment = next((a for a in assignments if a.artist_id == artist_id), None)
    cluster_of = {a.artist_id: a.cluster_id for a in assignments}
    proposed_id = propose_cluster(sorted_albums, {style.id: style for style in store.load(Style)})
    all_artists = store.load(Artist)
    connections = connections_of(artist_id, all_artists, store.load(ArtistEnrichment))

    def related(artist_ids: tuple[int, ...]) -> list[dict]:
        found = [a for a in all_artists if a.id in artist_ids]
        return [
            {"id": a.id, "name": a.name, "cluster": cluster_names.get(cluster_of.get(a.id))}
            for a in sorted(found, key=lambda a: sort_name(a.name))
        ]

    # Whom Discogs connects the artist to goes before its styles, when the connection is close.
    hint = cluster_hints(store).get(artist_id)
    names = {a.id: a.name for a in all_artists}
    located = {row.album_id: row for row in BrowseQueries(store).artist_albums(artist_id)}
    derived_year = _earliest_year(sorted_albums)
    shift = next((s for s in cluster_shifts(store) if s.artist_id == artist_id), None)
    return {
        "needs_attention": _needs_attention(artist, assignment, sorted_albums, shift),
        "cluster_name": cluster_names.get(assignment.cluster_id) if assignment else None,
        "shift": shift
        and {
            "current": cluster_names.get(shift.cluster_id),
            "proposed": cluster_names.get(shift.proposed_cluster_id),
            "titles": [album.title for album in albums if album.id in shift.album_ids],
        },
        "clusters": clusters,
        "assignment": assignment,
        "proposed_cluster": find_by_id(clusters, proposed_id),
        "connected_cluster": find_by_id(clusters, hint.cluster_id if hint else None),
        "connection_decides": bool(hint and hint.decisive),
        "related": {
            "other_names": related(connections.other_names),
            "bands": related(connections.bands),
            "members": related(connections.members),
        },
        "connected_artists": [
            {"id": other_id, "name": names[other_id]} for other_id in (hint.via_artist_ids if hint else ())
        ],
        "derived_year": derived_year,
        "band": band_of(artist.start_year or derived_year),
        "family": find_by_id(store.load(AliasGroup), artist.alias_group_id),
        "rules": described_rules(store, artist_id),
        "albums": sorted(
            ({"album": album, "place": located.get(album.id)} for album in albums),
            key=lambda row: (row["album"].original_release_year or 9999, row["album"].title.casefold()),
        ),
    }
