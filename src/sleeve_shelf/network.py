"""Application service for the Connections screen: the artists of the collection and what
ties them together — members and other names from Discogs, one name inside another,
families, one credited on an album of the other, the same song on albums of both, and the
same record label."""

import heapq
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, replace
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
from sleeve_shelf.ingestion.discogs_api import WRITER_ROLE
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
    # One credited on an album of the other: a musician, an arranger, a producer.
    CREDIT = "credit"
    # The same song on albums of both.
    SONGS = "songs"
    # Albums of both on one record label: of the pressing, so a reissue label counts too.
    LABEL = "label"


# The ties that show all of the other's albums; a credit or a song shows the albums it is on.
_ALL_ALBUMS = frozenset({Tie.NAME, Tie.MEMBER, Tie.BILLING, Tie.FAMILY})
# Ties that say two artists share something, rather than that they know each other.
LOOSE_TIES = frozenset({Tie.SONGS, Tie.LABEL})
# A label with more artists than this says little about any two of them, and would tie each
# to all the others. Discogs' own entry for what came out without a label is no label either.
MAX_LABEL_ARTISTS = 25
NO_LABEL = "not on label"


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


# Who is on the record: everyone credited but those behind it. Instruments and voices are too
# many to name, so what does not count is named instead.
_LOOKED_BACK = re.compile(r"executive|reissue|re-issue|compilation", re.IGNORECASE)
_MAKES_THE_MUSIC = re.compile(r"conduct|music(al)? direct|arrang|produc", re.IGNORECASE)
_BEHIND_THE_RECORD = re.compile(
    r"design|photo|liner|master(ed|ing)|lacquer|engineer|\bart\b|artwork|layout|cover|\bmix|recorded"
    r"|cut by|pressed|copyright|phonographic|manufactur|distribut|management|coordinat|illustrat"
    r"|typograph|sleeve|graphic|transfer|a&r|compiled|booking|legal|notes|edited|editor|technician"
    r"|tape|programm|research|supervis|lettering|painting|text by|translated|concept|^other|film"
    r"|video|direct|published|licensed|marketed|crew|assistant|consultant|restor|sound|overdub"
    r"|tuner|tuned|lighting|interview|dedicat|thanks|presenter|announcer",
    re.IGNORECASE,
)


def on_the_record(role: str) -> tuple[str, ...]:
    """The parts of a Discogs role that put someone on the record, without the remarks between
    brackets: "Piano [Grand], Liner Notes" is ("Piano",). Who wrote a song is not on the record
    for it: writing "Yesterdays" does not tie Jerome Kern to all who recorded it."""
    found = []
    for part in re.split(r",\s*(?![^\[]*\])", role):
        part = re.sub(r"\s*\[[^\]]*\]", "", part).strip()
        if not part or WRITER_ROLE.search(part) or _LOOKED_BACK.search(part):
            continue
        if _MAKES_THE_MUSIC.search(part) or not _BEHIND_THE_RECORD.search(part):
            found.append(part)
    return tuple(found)


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
class OnRecord:
    """An artist of the collection credited on an album of another."""

    album_id: int
    album_title: str
    album_artist_id: int
    artist_id: int
    name: str
    roles: tuple[str, ...]


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
class Heard:
    """A song on an album."""

    album_id: int
    artist_id: int
    title: str
    writers: frozenset[int]


def collection_songs(artists: list[Artist], albums: list[Album], releases: list[ReleaseEnrichment]) -> list[tuple[str, list[Heard]]]:
    """The songs of the collection, each as its key and the albums it is on.

    One title can be several songs: two tracks of the same title are one song when Discogs
    names a writer of both (Kern's "Yesterdays" is not Guns N' Roses'). A track without a
    writer belongs to its title's song only when the tracks with one are all one song; with
    none known at all, the title alone decides. A compilation ("Various") counts for no one.
    """
    various = {artist.id for artist in artists if is_various(artist)}
    tracklists = {release.release_id: release.tracklist or () for release in releases}
    by_key: dict[str, list[Heard]] = {}
    for album in sorted(albums, key=lambda a: a.id):
        if album.artist_id in various:
            continue
        for track in tracklists.get(album.release_id, ()):
            key = song_key(track.title)
            if key not in _NO_SONG:
                heard = Heard(album.id, album.artist_id, track.title, frozenset(track.writers or ()))
                by_key.setdefault(key, []).append(heard)
    songs = []
    for key, heard in by_key.items():
        # Tracks sharing a writer, directly or through another track, are one song.
        groups: list[list[Heard]] = []
        for one in (h for h in heard if h.writers):
            joined = [group for group in groups if any(one.writers & other.writers for other in group)]
            groups = [group for group in groups if not any(group is j for j in joined)]
            groups.append([one, *(other for group in joined for other in group)])
        unknown = [h for h in heard if not h.writers]
        if len(groups) <= 1:
            groups = [(groups[0] if groups else []) + unknown]
        songs += [(key, sorted(group, key=lambda h: h.album_id)) for group in groups]
    return songs


def credited_on_albums(artists: list[Artist], albums: list[Album], releases: list[ReleaseEnrichment]) -> list[OnRecord]:
    """Each artist of the collection on the record of an album of another, once per album with
    all its roles. A compilation ("Various") counts for no one."""
    by_did = {a.discogs_artist_id: a for a in artists if a.discogs_artist_id is not None}
    various = {artist.id for artist in artists if is_various(artist)}
    credits = {release.release_id: release.credits or () for release in releases}
    found = []
    for album in sorted(albums, key=lambda a: a.id):
        if album.artist_id in various:
            continue
        roles: dict[int, dict[str, None]] = {}
        for credit in credits.get(album.release_id, ()):
            person = by_did.get(credit.discogs_artist_id)
            if person is None or person.id == album.artist_id or person.id in various:
                continue
            parts = on_the_record(credit.role)
            if parts:
                roles.setdefault(person.id, {}).update(dict.fromkeys(parts))
        names = {a.id: a.name for a in artists if a.id in roles}
        found += [
            OnRecord(album.id, album.title, album.artist_id, person, names[person], tuple(parts))
            for person, parts in sorted(roles.items())
        ]
    return found


def labels_of_albums(artists: list[Artist], albums: list[Album], releases: list[ReleaseEnrichment]) -> dict[int, dict[int, str]]:
    """Per album the labels that can tie artists, by Discogs id: no "Not On Label", no compilation,
    no label with more artists than MAX_LABEL_ARTISTS."""
    various = {artist.id for artist in artists if is_various(artist)}
    of_release = {release.release_id: release.labels or () for release in releases}
    on_album: dict[int, dict[int, str]] = {}
    with_artists: dict[int, set[int]] = {}
    for album in albums:
        if album.artist_id in various:
            continue
        for label in of_release.get(album.release_id, ()):
            if not label.name.casefold().startswith(NO_LABEL):
                on_album.setdefault(album.id, {})[label.discogs_label_id] = label.name
                with_artists.setdefault(label.discogs_label_id, set()).add(album.artist_id)
    return {
        album_id: {i: name for i, name in labels.items() if len(with_artists[i]) <= MAX_LABEL_ARTISTS}
        for album_id, labels in on_album.items()
    }


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
) -> list[Tied]:
    """The ties of an artist with the albums that show them, oldest first."""
    by_artist: dict[int, list[Album]] = {}
    for album in sorted(albums, key=lambda a: (a.original_release_year or 9999, sort_name(a.title), a.id)):
        by_artist.setdefault(album.artist_id, []).append(album)
    album_labels = labels_of_albums(artists, albums, releases)
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
) -> Network:
    """The network of the collection's artists, from what the app knows of them.

    Discogs ties are read from both records: a band is a tie whether the person's record
    names it or the band's record names the person. Only artists in the collection are
    points; a song ties two artists when albums of both have it (see collection_songs), a compilation ("Various")
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

    # Per label: the artists with an album on it, and its name.
    artists_on: dict[int, set[int]] = {}
    label_names: dict[int, str] = {}
    owner_of = {album.id: album.artist_id for album in albums}
    for album_id, labels in labels_of_albums(artists, albums, releases).items():
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
            on_record=link.on_record if Tie.CREDIT in kinds else (),
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


def ties_of(store: JsonStore, shown: Network, artist_id: int, leave_out: frozenset[Tie] = frozenset()) -> list[Tied]:
    """The ties of one artist in the network, with the albums that show them; artists tied only
    by the kinds left out are not among them."""
    releases = store.load(ReleaseEnrichment) if store.exists(ReleaseEnrichment) else []
    albums = store.load(Album) if store.exists(Album) else []
    around = [pair for pair in shown.around(artist_id) if set(pair[1].ties) - leave_out]
    return tied_albums(around, artist_id, store.load(Artist), albums, releases)


def album_songs_elsewhere(store: JsonStore, album_id: int) -> list[tuple[str, tuple[int, ...]]]:
    """The songs of an album that other albums of the collection have too (see songs_elsewhere)."""
    if not store.exists(ReleaseEnrichment):
        return []
    return songs_elsewhere(album_id, store.load(Artist), store.load(Album), store.load(ReleaseEnrichment))


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
