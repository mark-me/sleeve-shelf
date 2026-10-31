"""The order albums stand in: cluster, era band, artist family, year, title."""

from collections import Counter, defaultdict
from dataclasses import dataclass

from sleeve_shelf.domain import (
    Album,
    AliasGroup,
    Artist,
    ArtistClusterAssignment,
    Cluster,
    Style,
    clusters_in_order,
    sort_name,
)
from sleeve_shelf.sorting.eras import band_index, band_of


@dataclass(frozen=True, slots=True)
class Unit:
    """What stays together on the shelf: one artist, or a family of artists."""

    name: str
    artist_ids: tuple[int, ...]
    cluster_id: int | None
    cluster_is_proposed: bool
    start_year: int | None
    band: str


@dataclass(frozen=True, slots=True)
class OrderedAlbum:
    album_id: int
    cluster_id: int | None
    band: str
    unit_name: str


def propose_cluster(albums: list[Album], styles: dict[int, Style]) -> int | None:
    """The cluster most of the albums' styles point to; a tie goes to the earliest album."""
    votes: Counter[int] = Counter()
    earliest: dict[int, int] = {}
    for album in albums:
        year = album.original_release_year or 9999
        for style_id in album.style_ids:
            if style_id in styles:
                cluster_id = styles[style_id].cluster_id
                votes[cluster_id] += 1
                earliest[cluster_id] = min(earliest.get(cluster_id, 9999), year)
    if not votes:
        return None
    return min(votes, key=lambda cluster_id: (-votes[cluster_id], earliest[cluster_id], cluster_id))


def build_units(
    artists: list[Artist],
    albums: list[Album],
    assignments: list[ArtistClusterAssignment],
    alias_groups: list[AliasGroup],
    styles: list[Style],
    connected: dict[int, int] | None = None,
) -> list[Unit]:
    """Group the artists into units and settle each unit's cluster and era band.

    A unit none of whose artists has a cluster gets one proposed: the cluster of the
    artists Discogs connects it to (connected: artist id to cluster id), and without
    such a connection the cluster its albums' styles point to.
    """
    albums_by_artist: dict[int, list[Album]] = defaultdict(list)
    for album in albums:
        albums_by_artist[album.artist_id].append(album)
    assigned = {a.artist_id: a.cluster_id for a in assignments if a.cluster_id is not None}
    style_by_id = {style.id: style for style in styles}
    labels = {group.id: group.label for group in alias_groups}

    grouped: dict[object, list[Artist]] = defaultdict(list)
    for artist in artists:
        in_family = artist.alias_group_id in labels
        key = ("family", artist.alias_group_id) if in_family else ("artist", artist.id)
        grouped[key].append(artist)

    units = []
    for (kind, key), members in grouped.items():
        unit_albums = [album for member in members for album in albums_by_artist[member.id]]
        if not unit_albums:
            continue
        # A family stands in the cluster most of its albums were curated into.
        curated = Counter(
            assigned[member.id]
            for member in members
            if member.id in assigned
            for _ in albums_by_artist[member.id]
        )
        by_connection = Counter(
            connected[member.id]
            for member in members
            if connected and member.id in connected
            for _ in albums_by_artist[member.id]
        )
        if curated:
            cluster_id, proposed = curated.most_common(1)[0][0], False
        elif by_connection:
            # Who the artist belongs with says more than what the style tags say.
            cluster_id, proposed = by_connection.most_common(1)[0][0], True
        else:
            cluster_id = propose_cluster(unit_albums, style_by_id)
            proposed = cluster_id is not None
        known = [member.start_year for member in members if member.start_year]
        # Without a known start, the earliest original year in the collection stands in.
        years = known or [a.original_release_year for a in unit_albums if a.original_release_year]
        start_year = min(years, default=None)
        units.append(
            Unit(
                name=sort_name(labels[key] if kind == "family" else members[0].name),
                artist_ids=tuple(member.id for member in members),
                cluster_id=cluster_id,
                cluster_is_proposed=proposed,
                start_year=start_year,
                band=band_of(start_year),
            )
        )
    return units


def order_albums(
    units: list[Unit],
    albums: list[Album],
    clusters: list[Cluster],
    standing: dict[int, int] | None = None,
) -> list[OrderedAlbum]:
    """Every album of the units in shelf order.

    Clusters follow their curated position; within a cluster the era bands run
    oldest first. Albums without a cluster come at the very end.

    Within a band the units, and within a unit its albums, keep the order they stand
    in now (standing: album -> its place along the walked shelves): that order is the
    owner's own, and the sorting has no rule that says otherwise. Only what stands
    nowhere yet goes by the rule — units alphabetically, an artist's albums by original
    year (unknown last) and title — before the first one standing that the rule puts
    after it. Without standing, everything goes by the rule.
    """
    standing = standing or {}
    position = {cluster.id: (index, cluster.id) for index, cluster in enumerate(clusters_in_order(clusters))}
    last = (len(clusters) + 1, 0)
    unit_of = {artist_id: unit for unit in units for artist_id in unit.artist_ids}
    placed = [album for album in albums if album.artist_id in unit_of]

    def album_rule(album: Album):
        return (album.original_release_year or 9999, album.title.casefold(), album.id)

    albums_of: dict[tuple[int, ...], list[Album]] = {}
    for album in placed:
        albums_of.setdefault(unit_of[album.artist_id].artist_ids, []).append(album)
    bands: dict[tuple, list[Unit]] = {}
    for unit in units:
        if unit.artist_ids in albums_of:
            bands.setdefault((position.get(unit.cluster_id, last), band_index(unit.band)), []).append(unit)

    def where(unit: Unit) -> float | None:
        # Where the unit stands now: the middle of its albums that stand, so a few kept
        # elsewhere don't move it.
        places = sorted(standing[a.id] for a in albums_of[unit.artist_ids] if a.id in standing)
        return places[len(places) // 2] if places else None

    ordered: list[OrderedAlbum] = []
    for band_key in sorted(bands):
        for unit in _keep_order(bands[band_key], where, lambda u: (u.name, u.artist_ids)):
            for album in _keep_order(albums_of[unit.artist_ids], lambda a: standing.get(a.id), album_rule):
                ordered.append(OrderedAlbum(album.id, unit.cluster_id, unit.band, unit.name))
    return ordered


def _keep_order(items: list, where, rule) -> list:
    """The items that stand somewhere in the order they stand in; each one that stands
    nowhere goes before the first standing one the rule puts after it, else at the end.
    Those that stand nowhere keep the rule's order among themselves."""
    result = sorted((item for item in items if where(item) is not None), key=where)
    standing_ones = {id(item) for item in result}
    for item in sorted((item for item in items if where(item) is None), key=rule):
        index = next(
            (k for k, other in enumerate(result) if id(other) in standing_ones and rule(other) > rule(item)),
            len(result),
        )
        result.insert(index, item)
    return result


def cluster_order_from_layout(layout_cluster_ids: list[int | None]) -> list[int]:
    """Read the sequence of the clusters off a layout.

    The layout is the cluster of each album in shelf order. A cluster counts
    where its longest unbroken run starts, so a few albums sampled elsewhere
    (a showcase shelf, external storage) don't move it.
    """
    best: dict[int, tuple[int, int]] = {}
    start = 0
    for index in range(1, len(layout_cluster_ids) + 1):
        ended = index == len(layout_cluster_ids) or layout_cluster_ids[index] != layout_cluster_ids[start]
        if not ended:
            continue
        cluster_id, length = layout_cluster_ids[start], index - start
        if cluster_id is not None and length > best.get(cluster_id, (0, 0))[0]:
            best[cluster_id] = (length, start)
        start = index
    return sorted(best, key=lambda cluster_id: best[cluster_id][1])
