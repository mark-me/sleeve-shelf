"""Application service for the Connections screen: the artists of the collection and what
ties them together — members and other names from Discogs, one name inside another,
families, and the same song on albums of both."""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    ArtistEnrichment,
    Cluster,
    ReleaseEnrichment,
    in_order,
)
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.sorting.families import names_inside, sort_name


class Tie(StrEnum):
    """What ties two artists, the closest first: a line is drawn as its closest tie."""

    # Another name of the same artist, as Discogs lists it.
    NAME = "name"
    # A person and a band the person is in, as Discogs lists it.
    MEMBER = "member"
    # One artist's name inside the other's: "Chet Baker Quartet" and "Chet Baker".
    BILLING = "billing"
    # Both in one family.
    FAMILY = "family"
    # The same song on albums of both.
    SONGS = "songs"


# Song titles that say nothing about the song, so two albums having one ties no one.
_NO_SONG = frozenset(
    {
        "",
        "intro",
        "introduction",
        "interlude",
        "outro",
        "theme",
        "the theme",
        "finale",
        "prelude",
        "reprise",
        "medley",
        "untitled",
        "silence",
        "hidden track",
        "vocal",
        "instrumental",
    }
)


def song_key(title: str) -> str:
    """A song title as songs are compared: without what stands between brackets, accents,
    punctuation, case, and a leading "The" — "'Round Midnight (Take 2)" is "round midnight"."""
    title = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", title)
    title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().casefold()
    title = " ".join(re.sub(r"[^a-z0-9]+", " ", title).split())
    return title.removeprefix("the ")


@dataclass(frozen=True, slots=True)
class Point:
    """An artist in the network."""

    artist_id: int
    name: str
    albums: int
    cluster_id: int | None


@dataclass(frozen=True, slots=True)
class Link:
    """What ties two artists; one is the lower id."""

    one: int
    other: int
    ties: tuple[Tie, ...]
    # The songs both have albums with, as the first of them titles it; with SONGS only.
    songs: tuple[str, ...] = ()


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


def build(
    artists: list[Artist],
    albums: list[Album],
    artist_records: list[ArtistEnrichment],
    releases: list[ReleaseEnrichment],
    assignments: list[ArtistClusterAssignment],
    clusters: list[Cluster],
) -> Network:
    """The network of the collection's artists, from what the app knows of them.

    Discogs ties are read from both records: a band is a tie whether the person's record
    names it or the band's record names the person. Only artists in the collection are
    points; a song ties two artists when albums of both have it.
    """
    ties: dict[tuple[int, int], set[Tie]] = {}
    songs_of: dict[tuple[int, int], set[str]] = {}

    def tie(one: int, other: int, kind: Tie) -> None:
        if one != other:
            ties.setdefault((min(one, other), max(one, other)), set()).add(kind)

    by_did = {a.discogs_artist_id: a.id for a in artists if a.discogs_artist_id is not None}
    for record in artist_records:
        artist_id = by_did.get(record.discogs_artist_id)
        if artist_id is None:
            continue
        for kind, discogs_ids in ((Tie.NAME, record.alias_ids), (Tie.MEMBER, record.member_ids), (Tie.MEMBER, record.group_ids)):
            for other in (by_did[d] for d in discogs_ids or () if d in by_did):
                tie(artist_id, other, kind)

    for artist_id, others in names_inside(artists).items():
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

    tracklists = {release.release_id: release.tracklist or () for release in releases}
    # Per song: the artists with an album that has it, and its title as first found.
    artists_with: dict[str, set[int]] = {}
    title_of: dict[str, str] = {}
    for album in sorted(albums, key=lambda a: a.id):
        for track in tracklists.get(album.release_id, ()):
            key = song_key(track.title)
            if key in _NO_SONG:
                continue
            artists_with.setdefault(key, set()).add(album.artist_id)
            title_of.setdefault(key, track.title)
    for key, having in artists_with.items():
        having = sorted(having)
        for index, one in enumerate(having):
            for other in having[index + 1 :]:
                tie(one, other, Tie.SONGS)
                songs_of.setdefault((one, other), set()).add(key)

    order = list(Tie)
    links = tuple(
        Link(
            one,
            other,
            tuple(sorted(kinds, key=order.index)),
            tuple(sorted((title_of[key] for key in songs_of.get((one, other), ())), key=song_key)),
        )
        for (one, other), kinds in sorted(ties.items())
    )
    counts = Counter(album.artist_id for album in albums)
    cluster_of = {a.artist_id: a.cluster_id for a in assignments}
    points = tuple(
        Point(artist.id, artist.name, counts[artist.id], cluster_of.get(artist.id))
        for artist in sorted(artists, key=lambda a: a.id)
    )
    return Network(points, links, tuple((c.id, c.name) for c in in_order(clusters)))


def network(store: JsonStore) -> Network:
    """The network of the collection as it stands."""
    if not store.exists(Artist):
        return Network((), (), ())

    def load(entity):
        return store.load(entity) if store.exists(entity) else []

    return build(
        store.load(Artist),
        load(Album),
        load(ArtistEnrichment),
        load(ReleaseEnrichment),
        load(ArtistClusterAssignment),
        load(Cluster),
    )
