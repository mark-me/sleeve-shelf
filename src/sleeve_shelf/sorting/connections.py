"""Clusters by connection: the cluster of the artists Discogs connects an artist to."""

from collections import Counter
from dataclasses import dataclass

from sleeve_shelf.domain import Artist, artist_ids_by_discogs_id, ArtistClusterAssignment, ArtistEnrichment
from sleeve_shelf.sorting.families import MAX_BANDS


@dataclass(frozen=True, slots=True)
class ClusterHint:
    """The cluster an artist's connections stand in, and the connections it is read from."""

    cluster_id: int
    # The connected artists in that cluster, the one with the most albums first.
    via_artist_ids: tuple[int, ...]
    # Whether the connection is close enough to propose the cluster by: another name of the
    # artist, or a person and a band of their own. A band shared with others, or a
    # sideman's, is an indication only.
    decisive: bool = True


@dataclass(frozen=True, slots=True)
class Connections:
    """The artists in the collection Discogs connects one artist to: artist ids."""

    other_names: tuple[int, ...] = ()
    # The bands the artist is in, and the members of the artist when it is a band.
    bands: tuple[int, ...] = ()
    members: tuple[int, ...] = ()


def connections_of(
    artist_id: int, artists: list[Artist], enrichments: list[ArtistEnrichment]
) -> Connections:
    """Whom Discogs connects the artist to, by what they are to each other.

    Read from both records: a band is listed when the artist's record names it or
    the band's record names the artist. Only artists in the collection are known.
    """
    by_did = artist_ids_by_discogs_id(artists)
    names: set[int] = set()
    bands: set[int] = set()
    members: set[int] = set()
    for record in enrichments:
        owner = by_did.get(record.discogs_artist_id)
        if owner is None:
            continue
        aliases = {by_did[d] for d in record.alias_ids or () if d in by_did}
        groups = {by_did[d] for d in record.group_ids or () if d in by_did}
        listed = {by_did[d] for d in record.member_ids or () if d in by_did}
        if owner == artist_id:
            names |= aliases
            bands |= groups
            members |= listed
        else:
            if artist_id in aliases:
                names.add(owner)
            if artist_id in groups:
                members.add(owner)
            if artist_id in listed:
                bands.add(owner)
    return Connections(
        *(tuple(sorted(found - {artist_id})) for found in (names, bands, members))
    )


def clusters_by_connection(
    artists: list[Artist],
    assignments: list[ArtistClusterAssignment],
    enrichments: list[ArtistEnrichment],
    album_counts: dict[int, int],
    max_bands: int = MAX_BANDS,
) -> dict[int, ClusterHint]:
    """For each artist without a confirmed cluster: the cluster of whom Discogs connects it to.

    Only direct connections count: the artist's other names, the bands a person is in,
    and the members of a band — whichever of the two records names the other. A fellow
    member's other bands are not followed.

    The close connections are the ones a family is suggested from: other names, and a
    person with a band that no other artist in the collection is in, unless the person is
    a sideman (in more than max_bands bands of the collection). With any of those the hint is decisive and goes by them alone. Otherwise it
    goes by the loose ones — a band several artists share, a sideman's bands — and is no
    more than an indication: measured against the curated collection those are right
    about as often as the styles are.

    With connections in several clusters, the cluster holding most of their albums wins,
    and on a tie the one of the connection with the most albums.
    """
    by_did = artist_ids_by_discogs_id(artists)

    # Other names of one artist count as that one artist: same_as leads to one of them.
    same_as = {artist_id: artist_id for artist_id in by_did.values()}

    def root(artist_id: int) -> int:
        while same_as[artist_id] != artist_id:
            artist_id = same_as[artist_id]
        return artist_id

    aliases: set[tuple[int, int]] = set()
    bands_of: dict[int, set[int]] = {artist_id: set() for artist_id in by_did.values()}
    for record in enrichments:
        artist_id = by_did.get(record.discogs_artist_id)
        if artist_id is None:
            continue
        for other in (by_did[d] for d in record.alias_ids or () if d in by_did):
            if other != artist_id:
                aliases.add((artist_id, other))
                same_as[root(other)] = root(artist_id)
        for band in (by_did[d] for d in record.group_ids or () if d in by_did):
            if band != artist_id:
                bands_of[artist_id].add(band)
        for member in (by_did[d] for d in record.member_ids or () if d in by_did):
            if member != artist_id:
                bands_of[member].add(artist_id)

    # Who a band belongs to: the artists in it that are no sidemen, each under one name.
    owners: dict[int, set[int]] = {}
    for person, bands in bands_of.items():
        if len(bands) <= max_bands:
            for band in bands:
                owners.setdefault(band, set()).add(root(person))

    close: dict[int, set[int]] = {}
    loose: dict[int, set[int]] = {}

    def connect(kind: dict[int, set[int]], one: int, other: int) -> None:
        kind.setdefault(one, set()).add(other)
        kind.setdefault(other, set()).add(one)

    for one, other in aliases:
        connect(close, one, other)
    for person, bands in bands_of.items():
        for band in bands:
            own = len(bands) <= max_bands and owners.get(band) == {root(person)}
            connect(close if own else loose, person, band)

    curated = {a.artist_id: a.cluster_id for a in assignments if a.confirmed}

    def hint(others: set[int], decisive: bool) -> ClusterHint | None:
        # A connection counts by its albums; one without any still counts once.
        weight = {other: max(album_counts.get(other, 0), 1) for other in others if other in curated}
        if not weight:
            return None
        votes: Counter[int] = Counter()
        largest: dict[int, int] = {}
        for other, albums in weight.items():
            votes[curated[other]] += albums
            largest[curated[other]] = max(largest.get(curated[other], 0), albums)
        cluster_id = min(votes, key=lambda c: (-votes[c], -largest[c], c))
        via = sorted(
            (other for other in weight if curated[other] == cluster_id),
            key=lambda other: (-weight[other], other),
        )
        return ClusterHint(cluster_id, tuple(via), decisive)

    hints: dict[int, ClusterHint] = {}
    for artist_id in sorted(close.keys() | loose.keys()):
        if artist_id in curated:
            continue
        found = hint(close.get(artist_id, set()), True) or hint(loose.get(artist_id, set()), False)
        if found is not None:
            hints[artist_id] = found
    return hints
