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


# Discogs' artist for a compilation: its songs are by many artists, so it shares none.
_VARIOUS_DISCOGS_ID = 194
_VARIOUS_NAMES = frozenset({"various", "various artists"})

# What stands between brackets at the end of a title: "(Live)", "(Take 2)", "[Bonus Track]".
_TRAILING_BRACKETS = re.compile(r"\s*(\([^()]*\)|\[[^\[\]]*\])\s*$")


def is_various(artist: Artist) -> bool:
    """Whether the artist is Discogs' "Various", of compilations."""
    return artist.discogs_artist_id == _VARIOUS_DISCOGS_ID or artist.name.casefold() in _VARIOUS_NAMES


def song_key(title: str) -> str:
    """A song title as songs are compared: without what stands between brackets at its end,
    accents, punctuation, case, and a leading "The" — "'Round Midnight (Take 2)" is "round
    midnight". Brackets at the start belong to the title: "(Dance With The) Guitar Man" is
    another song than "Guitar Man"."""
    # A title that is all brackets ("(Nice Dream)") keeps them.
    while (shorter := _TRAILING_BRACKETS.sub("", title)) != title and shorter.strip():
        title = shorter
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


@dataclass(frozen=True, slots=True)
class _Heard:
    """A song on an album."""

    album_id: int
    artist_id: int
    title: str
    writers: frozenset[int]


def _songs(artists: list[Artist], albums: list[Album], releases: list[ReleaseEnrichment]) -> list[tuple[str, list[_Heard]]]:
    """The songs of the collection, each as its key and the albums it is on.

    One title can be several songs: two tracks of the same title are one song when Discogs
    names a writer of both (Kern's "Yesterdays" is not Guns N' Roses'). A track without a
    writer belongs to its title's song only when the tracks with one are all one song; with
    none known at all, the title alone decides. A compilation ("Various") counts for no one.
    """
    various = {artist.id for artist in artists if is_various(artist)}
    tracklists = {release.release_id: release.tracklist or () for release in releases}
    by_key: dict[str, list[_Heard]] = {}
    for album in sorted(albums, key=lambda a: a.id):
        if album.artist_id in various:
            continue
        for track in tracklists.get(album.release_id, ()):
            key = song_key(track.title)
            if key not in _NO_SONG:
                heard = _Heard(album.id, album.artist_id, track.title, frozenset(track.writers or ()))
                by_key.setdefault(key, []).append(heard)
    songs = []
    for key, heard in by_key.items():
        # Tracks sharing a writer, directly or through another track, are one song.
        groups: list[list[_Heard]] = []
        for one in (h for h in heard if h.writers):
            joined = [group for group in groups if any(one.writers & other.writers for other in group)]
            groups = [group for group in groups if not any(group is j for j in joined)]
            groups.append([one, *(other for group in joined for other in group)])
        unknown = [h for h in heard if not h.writers]
        if len(groups) <= 1:
            groups = [(groups[0] if groups else []) + unknown]
        songs += [(key, sorted(group, key=lambda h: h.album_id)) for group in groups]
    return songs


@dataclass(frozen=True, slots=True)
class TiedAlbum:
    """An album that shows a tie: with a shared song, the songs it has of them."""

    album_id: int
    songs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Tied:
    """An artist tied to the one in the middle, with the albums to take from the shelf."""

    point: Point
    link: Link
    # The other's albums: all of them, unless a song is all that ties the two — then those
    # that have one.
    theirs: tuple[TiedAlbum, ...]
    # With shared songs: the albums of the artist in the middle that have one.
    mine: tuple[TiedAlbum, ...] = ()


def tied_albums(
    around: list[tuple[Point, Link]],
    artist_id: int,
    artists: list[Artist],
    albums: list[Album],
    releases: list[ReleaseEnrichment],
) -> list[Tied]:
    """The ties of an artist with the albums that show them, oldest first."""
    by_artist: dict[int, list[Album]] = {}
    for album in sorted(albums, key=lambda a: (a.original_release_year or 9999, sort_name(a.title), a.id)):
        by_artist.setdefault(album.artist_id, []).append(album)
    # Per other artist: the songs on each album, of those shared with this artist.
    shared: dict[int, dict[int, list[str]]] = {}
    for _, heard in _songs(artists, albums, releases):
        having = {h.artist_id for h in heard}
        if artist_id not in having:
            continue
        for other in having:
            for h in heard:
                if h.artist_id in (artist_id, other):
                    titles = shared.setdefault(other, {}).setdefault(h.album_id, [])
                    if h.title not in titles:
                        titles.append(h.title)

    def having(owner: int, songs: dict[int, list[str]], every: bool = False) -> tuple[TiedAlbum, ...]:
        return tuple(
            TiedAlbum(album.id, tuple(songs.get(album.id, ())))
            for album in by_artist.get(owner, [])
            if every or album.id in songs
        )

    result = []
    for point, link in around:
        songs = shared.get(point.artist_id, {}) if Tie.SONGS in link.ties else {}
        # A band, a family, another name: all its albums, each with the shared songs it has.
        every = link.ties != (Tie.SONGS,)
        result.append(Tied(point, link, having(point.artist_id, songs, every), having(artist_id, songs)))
    return result


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
    points; a song ties two artists when albums of both have it (see _songs), a compilation ("Various")
    tying no one.
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

    # Per song: its title as first found, and the artists with an album that has it.
    title_of: dict[str, str] = {}
    for key, heard in _songs(artists, albums, releases):
        title_of.setdefault(key, heard[0].title)
        having = sorted({h.artist_id for h in heard})
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


def ties_of(store: JsonStore, shown: Network, artist_id: int) -> list[Tied]:
    """The ties of one artist in the network, with the albums that show them."""
    releases = store.load(ReleaseEnrichment) if store.exists(ReleaseEnrichment) else []
    albums = store.load(Album) if store.exists(Album) else []
    return tied_albums(shown.around(artist_id), artist_id, store.load(Artist), albums, releases)


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
