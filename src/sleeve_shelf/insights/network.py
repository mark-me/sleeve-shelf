"""The network of the artists of the collection and what ties them together — members and
other names from Discogs, one name inside another, families, one credited on an album of the
other, the same song on albums of both, and the same record label. No storage in here."""

import heapq
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, replace

from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    ArtistEnrichment,
    Cluster,
    ReleaseEnrichment,
    artist_ids_by_discogs_id,
    in_order,
    sort_name,
)
from sleeve_shelf.insights.ties import (
    Tie,
    LOOSE_TIES,
    song_key,
    OnRecord,
    collection_songs,
    credited_on_albums,
    side_players,
    musicians_as_points,
    labels_of_albums,
)
from sleeve_shelf.sorting.families import names_inside


# The ties that show all of the other's albums; a credit or a song shows the albums it is on.
_ALL_ALBUMS = frozenset({Tie.NAME, Tie.MEMBER, Tie.BILLING, Tie.FAMILY})


@dataclass(frozen=True, slots=True)
class Point:
    """An artist in the network."""

    artist_id: int
    name: str
    albums: int
    cluster_id: int | None

    @property
    def is_musician(self) -> bool:
        """A musician without an album in the collection: no artist, so its id is below zero."""
        return self.artist_id < 0


@dataclass(frozen=True, slots=True)
class Link:
    """What ties two artists; one is the lower id."""

    one: int
    other: int
    ties: tuple[Tie, ...]
    # The songs both have albums with, as the first of them titles it; with SONGS only.
    songs: tuple[str, ...] = ()
    # Who of the two is credited on which album of the other; with CREDIT only.
    on_record: tuple[OnRecord, ...] = ()
    # The record labels both have albums on; with LABEL only.
    labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Network:
    points: tuple[Point, ...]
    links: tuple[Link, ...]
    # The clusters in their order on the shelves, as (id, name).
    clusters: tuple[tuple[int, str], ...]

    def around(self, artist_id: int) -> list[tuple[Point, Link]]:
        """The artists tied to this one, with what ties them: the closest tie first, then the
        most songs, then by name."""
        points = {point.artist_id: point for point in self.points}
        found = [
            (points[link.other if link.one == artist_id else link.one], link)
            for link in self.links
            if artist_id in (link.one, link.other)
        ]
        order = list(Tie)
        return sorted(
            found,
            key=lambda pair: (order.index(pair[1].ties[0]), -len(pair[1].songs), sort_name(pair[0].name)),
        )


@dataclass(frozen=True, slots=True)
class TiedAlbum:
    """An album that shows a tie: the shared songs it has, who of the two is credited on it, and
    the shared labels it is on."""

    album_id: int
    songs: tuple[str, ...] = ()
    credits: tuple[OnRecord, ...] = ()
    labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Tied:
    """An artist tied to the one in the middle, with the albums to take from the shelf."""

    point: Point
    link: Link
    # The other's albums: all of them with a band, a family or a name; with only a song, a
    # credit or a label between the two, those it is on.
    theirs: tuple[TiedAlbum, ...]
    # The albums of the artist in the middle with a shared song or label, or the other's credit.
    mine: tuple[TiedAlbum, ...] = ()


def tied_albums(
    around: list[tuple[Point, Link]],
    artist_id: int,
    artists: list[Artist],
    albums: list[Album],
    releases: list[ReleaseEnrichment],
    labels_left_out: Iterable[str] = (),
) -> list[Tied]:
    """The ties of an artist with the albums that show them, oldest first."""
    by_artist: dict[int, list[Album]] = {}
    for album in sorted(albums, key=lambda a: (a.original_release_year or 9999, sort_name(a.title), a.id)):
        by_artist.setdefault(album.artist_id, []).append(album)
    album_labels = labels_of_albums(artists, albums, releases, labels_left_out)
    # Per other artist: the songs on each album, of those shared with this artist.
    shared: dict[int, dict[int, list[str]]] = {}
    for _, heard in collection_songs(artists, albums, releases):
        having = {h.artist_id for h in heard}
        if artist_id not in having:
            continue
        for other in having:
            for h in heard:
                if h.artist_id in (artist_id, other):
                    titles = shared.setdefault(other, {}).setdefault(h.album_id, [])
                    if h.title not in titles:
                        titles.append(h.title)

    def having(owner: int, link: Link, songs: dict[int, list[str]], every: bool = False) -> tuple[TiedAlbum, ...]:
        on_record: dict[int, list[OnRecord]] = {}
        for entry in link.on_record:
            on_record.setdefault(entry.album_id, []).append(entry)

        def shared_labels(album_id: int) -> tuple[str, ...]:
            return tuple(name for name in album_labels.get(album_id, {}).values() if name in link.labels)

        return tuple(
            TiedAlbum(album.id, tuple(songs.get(album.id, ())), tuple(on_record.get(album.id, ())), shared_labels(album.id))
            for album in by_artist.get(owner, [])
            if every or album.id in songs or album.id in on_record or shared_labels(album.id)
        )

    result = []
    for point, link in around:
        songs = shared.get(point.artist_id, {}) if Tie.SONGS in link.ties else {}
        every = bool(_ALL_ALBUMS & set(link.ties))
        result.append(Tied(point, link, having(point.artist_id, link, songs, every), having(artist_id, link, songs)))
    return result


def build(
    artists: list[Artist],
    albums: list[Album],
    artist_records: list[ArtistEnrichment],
    releases: list[ReleaseEnrichment],
    assignments: list[ArtistClusterAssignment],
    clusters: list[Cluster],
    labels_left_out: Iterable[str] = (),
    unrelated: frozenset[tuple[int, int]] | set[tuple[int, int]] = frozenset(),
) -> Network:
    """The network of the collection's artists, from what the app knows of them.

    Discogs ties are read from both records: a band is a tie whether the person's record
    names it or the band's record names the person. The artists in the collection are
    points, and musicians on enough of their albums (see musicians_as_points); a song ties two artists when albums of both have it (see collection_songs), a compilation ("Various")
    tying no one.
    """
    ties: dict[tuple[int, int], set[Tie]] = {}
    songs_of: dict[tuple[int, int], set[str]] = {}

    def tie(one: int, other: int, kind: Tie) -> None:
        if one != other:
            ties.setdefault((min(one, other), max(one, other)), set()).add(kind)

    by_did = artist_ids_by_discogs_id(artists)
    for record in artist_records:
        artist_id = by_did.get(record.discogs_artist_id)
        if artist_id is None:
            continue
        for kind, discogs_ids in ((Tie.NAME, record.alias_ids), (Tie.MEMBER, record.member_ids), (Tie.MEMBER, record.group_ids)):
            for other in (by_did[d] for d in discogs_ids or () if d in by_did):
                tie(artist_id, other, kind)

    for artist_id, others in names_inside(artists, unrelated).items():
        for other in others:
            tie(artist_id, other, Tie.BILLING)

    families: dict[int, list[int]] = {}
    for artist in artists:
        if artist.alias_group_id is not None:
            families.setdefault(artist.alias_group_id, []).append(artist.id)
    for members in families.values():
        for index, one in enumerate(members):
            for other in members[index + 1 :]:
                tie(one, other, Tie.FAMILY)

    # Per song: its title as first found, and the artists with an album that has it.
    title_of: dict[str, str] = {}
    for key, heard in collection_songs(artists, albums, releases):
        title_of.setdefault(key, heard[0].title)
        having = sorted({h.artist_id for h in heard})
        for index, one in enumerate(having):
            for other in having[index + 1 :]:
                tie(one, other, Tie.SONGS)
                songs_of.setdefault((one, other), set()).add(key)

    on_record: dict[tuple[int, int], list[OnRecord]] = {}
    for entry in credited_on_albums(artists, albums, releases):
        tie(entry.album_artist_id, entry.artist_id, Tie.CREDIT)
        pair = (min(entry.album_artist_id, entry.artist_id), max(entry.album_artist_id, entry.artist_id))
        on_record.setdefault(pair, []).append(entry)

    # A musician without an album in the collection: an id of its own, below those of artists.
    players = side_players(artists, albums, artist_records, releases)
    musicians = musicians_as_points(players, artists)
    musician_names: dict[int, str] = {}
    musician_albums: Counter[int] = Counter()
    for player in players:
        if player.discogs_id in musicians:
            point = -player.discogs_id
            tie(point, player.album_artist_id, Tie.SESSION)
            on_record.setdefault((point, player.album_artist_id), []).append(
                OnRecord(player.album_id, player.album_title, player.album_artist_id, point, player.name, player.roles)
            )
            musician_names[point] = player.name
            musician_albums[point] += 1

    # Per label: the artists with an album on it, and its name.
    artists_on: dict[int, set[int]] = {}
    label_names: dict[int, str] = {}
    owner_of = {album.id: album.artist_id for album in albums}
    for album_id, labels in labels_of_albums(artists, albums, releases, labels_left_out).items():
        for label_id, name in labels.items():
            artists_on.setdefault(label_id, set()).add(owner_of[album_id])
            label_names[label_id] = name
    labels_of: dict[tuple[int, int], set[str]] = {}
    for label_id, having in artists_on.items():
        having = sorted(having)
        for index, one in enumerate(having):
            for other in having[index + 1 :]:
                tie(one, other, Tie.LABEL)
                labels_of.setdefault((one, other), set()).add(label_names[label_id])

    order = list(Tie)
    links = tuple(
        Link(
            one,
            other,
            tuple(sorted(kinds, key=order.index)),
            tuple(sorted((title_of[key] for key in songs_of.get((one, other), ())), key=song_key)),
            tuple(on_record.get((one, other), ())),
            tuple(sorted(labels_of.get((one, other), ()), key=sort_name)),
        )
        for (one, other), kinds in sorted(ties.items())
    )
    counts = Counter(album.artist_id for album in albums)
    cluster_of = {a.artist_id: a.cluster_id for a in assignments}
    points = tuple(
        Point(artist.id, artist.name, counts[artist.id], cluster_of.get(artist.id))
        for artist in sorted(artists, key=lambda a: a.id)
    )
    points += tuple(Point(point, name, musician_albums[point], None) for point, name in sorted(musician_names.items()))
    return Network(points, links, tuple((c.id, c.name) for c in in_order(clusters)))


# What a step along a way costs: a song or label shared is a looser tie than a band, a family or
# a name, so a way goes by those where it can.
_STEP = 1


_SONG_STEP = 3


def way(shown: Network, start: int, end: int, switched: set[Tie] | frozenset[Tie]) -> list[tuple[Point, Link | None]] | None:
    """The shortest way from one artist to another along the ties switched on, as each artist
    with the tie that leads to it (none for the first); None when there is no way.

    A step by a song or label alone counts as three, so the way goes by closer ties where it can; of
    two ways as long, the one with fewer steps. A tie on the way names only the kinds that
    are switched on.
    """
    points = {point.artist_id: point for point in shown.points}
    if start not in points or end not in points:
        return None
    next_to: dict[int, list[tuple[int, Link, int]]] = {}
    for link in shown.links:
        kinds = tuple(tie for tie in link.ties if tie in switched)
        if not kinds:
            continue
        step = replace(
            link,
            ties=kinds,
            songs=link.songs if Tie.SONGS in kinds else (),
            on_record=link.on_record if Tie.CREDIT in kinds or Tie.SESSION in kinds else (),
            labels=link.labels if Tie.LABEL in kinds else (),
        )
        cost = _SONG_STEP if LOOSE_TIES.issuperset(kinds) else _STEP
        next_to.setdefault(link.one, []).append((link.other, step, cost))
        next_to.setdefault(link.other, []).append((link.one, step, cost))
    came_by: dict[int, tuple[int, Link] | None] = {start: None}
    best = {start: (0, 0)}
    queue = [(0, 0, start)]
    while queue:
        cost, steps, artist_id = heapq.heappop(queue)
        if artist_id == end:
            break
        if (cost, steps) > best[artist_id]:
            continue
        for other, link, step_cost in next_to.get(artist_id, ()):
            reached = (cost + step_cost, steps + 1)
            if other not in best or reached < best[other]:
                best[other] = reached
                came_by[other] = (artist_id, link)
                heapq.heappush(queue, (*reached, other))
    if end not in came_by:
        return None
    found: list[tuple[Point, Link | None]] = []
    artist_id = end
    while came_by[artist_id] is not None:
        before, link = came_by[artist_id]
        found.append((points[artist_id], link))
        artist_id = before
    found.append((points[start], None))
    return found[::-1]


def songs_elsewhere(
    album_id: int, artists: list[Artist], albums: list[Album], releases: list[ReleaseEnrichment]
) -> list[tuple[str, tuple[int, ...]]]:
    """The songs of an album that other albums of the collection have too, in the album's
    order, each as its title on this album and those other albums — of any artist, the same
    one included (a live record, a compilation of its own)."""
    others: dict[str, list[int]] = {}
    title_here: dict[str, str] = {}
    for key, heard in collection_songs(artists, albums, releases):
        here = [h for h in heard if h.album_id == album_id]
        if not here:
            continue
        title_here.setdefault(key, here[0].title)
        found = others.setdefault(key, [])
        for h in heard:
            if h.album_id != album_id and h.album_id not in found:
                found.append(h.album_id)
    release_id = next((album.release_id for album in albums if album.id == album_id), None)
    tracks = next((r.tracklist or () for r in releases if r.release_id == release_id), ())
    # Where each song first comes on the album.
    position = {song_key(track.title): index for index, track in reversed(list(enumerate(tracks)))}
    return [
        (title_here[key], tuple(found))
        for key, found in sorted(others.items(), key=lambda item: (position.get(item[0], len(tracks)), item[0]))
        if found
    ]
