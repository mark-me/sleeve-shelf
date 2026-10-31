"""Application service for the figures on an artist's and an album's page and the Statistics screen.

What the collection says about one artist or album, and who and what recurs across all of it.
"""

import random
from collections import Counter, deque
from dataclasses import dataclass
from datetime import date

from sleeve_shelf.config import load_settings
from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    ArtistEnrichment,
    Cluster,
    Placement,
    ReleaseEnrichment,
    Style,
    artists_by_discogs_id,
    credits_by_release,
    plain_name,
    sort_name,
)
from sleeve_shelf.insights.connections import album_songs_elsewhere, network
from sleeve_shelf.insights.network import Network
from sleeve_shelf.insights.ties import (
    LOOSE_TIES,
    NO_LABEL,
    OnRecord,
    collection_songs,
    credited_on_albums,
    is_various,
    musicians_as_points,
    named_in,
    on_the_record,
    side_players,
)
from sleeve_shelf.persistence import JsonStore

# Someone on at least this many of an artist's albums is one it keeps recording with.
COMPANION_ALBUMS = 2
COMPANIONS = 6
# How many a list on the Statistics screen holds.
TOP = 20

# Albums with at least this many people in common with an album are "with the same people".
ALIKE_PEOPLE = 2
ALIKE_ALBUMS = 5

# How many artists the list of the most connected holds.
HUBS = 10
# How many albums "from this year, long ago" shows, and how long ago that is.
LONG_AGO_ALBUMS = 6
LONG_AGO_YEARS = 50


@dataclass(frozen=True, slots=True)
class Person:
    """Someone credited across albums.

    Attributes:
        name: The name, without Discogs' "(2)".
        artist_id: Set when the person is an artist in the collection.
        roles: What they do, the most frequent first.
        album_ids: The albums they are on.
        point_id: Set when a musician with a point of their own in the network.
    """

    name: str
    artist_id: int | None
    roles: tuple[str, ...]
    album_ids: tuple[int, ...]
    point_id: int | None = None


@dataclass(frozen=True, slots=True)
class ArtistFigures:
    """What the collection says about one artist.

    Attributes:
        albums: The number of albums.
        rank: The artist's place among those with the most albums; None for a compilation's
            "Various".
        rank_shared: Whether others have as many.
        width_cm: How much room what stands on a shelf takes.
        shelves: On how many shelves it stands.
        styles: Albums per style, the most first: an album can have several.
        years: Albums per original year, every year from the first to the last.
        companions: Who is credited on several of the albums.
        appears_on: Albums of others the artist is on.
    """

    albums: int
    rank: int | None
    rank_shared: bool
    width_cm: float
    shelves: int
    styles: tuple[tuple[str, int], ...]
    years: tuple[tuple[int, int], ...]
    companions: tuple[Person, ...]
    appears_on: tuple[OnRecord, ...]


@dataclass(frozen=True, slots=True)
class AlbumFigures:
    """What the collection says about one album.

    Attributes:
        tracks: The number of songs.
        minutes: How long the songs last together; None unless Discogs gives every length.
        writers: Who wrote the songs, with on how many of them.
        position: Its place among the artist's albums by original year.
        of_artist: How many of the artist's albums have a year.
        earlier: The album before it by year.
        later: The album after it by year.
        same_year: The other albums of its original year.
        styles: Its styles, each with the albums of the collection that have it.
        labels: Its labels as (name, albums of the collection on it, catalogue number).
        people: Who is on it; each person's album_ids are all their albums in the collection.
        alike: Other albums with several of the same people, with those people.
        songs_elsewhere: How many of its songs other albums have too.
    """

    tracks: int
    minutes: int | None
    writers: tuple[tuple[str, int], ...]
    position: int | None
    of_artist: int
    earlier: int | None
    later: int | None
    same_year: tuple[int, ...]
    styles: tuple[tuple[str, int], ...]
    labels: tuple[tuple[str, int, str], ...]
    people: tuple[Person, ...]
    alike: tuple[tuple[int, tuple[str, ...]], ...]
    songs_elsewhere: int


@dataclass(frozen=True, slots=True)
class RecordedSong:
    """A song on albums of several artists.

    Attributes:
        title: The title.
        artists: On albums of how many artists.
        album_ids: The albums it is on.
    """

    title: str
    artists: int
    album_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CountedLabel:
    """A record label with the albums on it.

    Attributes:
        name: The label.
        album_ids: The albums on it.
    """

    name: str
    album_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Hub:
    """An artist with its number of close ties: anything but a shared song or label.

    Attributes:
        artist_id: The artist.
        name: The name.
        ties: The number of close ties.
    """

    artist_id: int
    name: str
    ties: int


@dataclass(frozen=True, slots=True)
class LongestWay:
    """The two artists furthest apart along close ties, of those a way leads between.

    Attributes:
        one: The one artist.
        one_name: Its name.
        other: The other artist.
        other_name: Its name.
        steps: How many steps lie between them.
    """

    one: int
    one_name: str
    other: int
    other_name: str
    steps: int


@dataclass(frozen=True, slots=True)
class CountedCluster:
    """A cluster with its number of albums.

    Attributes:
        cluster_id: The cluster; None for the albums of artists without a cluster.
        name: Its name.
        albums: The number of albums.
    """

    cluster_id: int | None
    name: str | None
    albums: int


@dataclass(frozen=True, slots=True)
class CollectionFigures:
    """Who and what recurs across the collection.

    Attributes:
        sidemen: Who is credited on the most albums of others.
        songs: The songs on albums of the most artists.
        labels: The labels with the most albums.
        hubs: The artists with the most close ties.
        longest_way: The two artists furthest apart, if a way leads between any.
        decades: Albums per decade, every decade from the first to the last.
        without_year: The albums without a year.
        clusters: Albums per cluster, the most first.
        credits_fetched: Whether the fetch run has brought credits yet, for all or part of the
            collection.
        labels_fetched: Whether it has brought labels yet.
    """

    sidemen: tuple[Person, ...]
    songs: tuple[RecordedSong, ...]
    labels: tuple[CountedLabel, ...]
    hubs: tuple[Hub, ...]
    longest_way: LongestWay | None
    decades: tuple[tuple[int, int], ...]
    without_year: int
    clusters: tuple[CountedCluster, ...]
    credits_fetched: bool
    labels_fetched: bool


def _people(
    entries: list[tuple[int, int, str, tuple[str, ...]]], by_did: dict[int, Artist], musicians: set[int]
) -> list[Person]:
    """People from (album, Discogs id, name, roles), those on the most albums first."""
    names: dict[int, str] = {}
    albums: dict[int, set[int]] = {}
    roles: dict[int, Counter[str]] = {}
    for album_id, discogs_id, name, parts in entries:
        names.setdefault(discogs_id, plain_name(name))
        albums.setdefault(discogs_id, set()).add(album_id)
        roles.setdefault(discogs_id, Counter()).update(parts)
    people = [
        Person(
            names[discogs_id],
            by_did[discogs_id].id if discogs_id in by_did else None,
            tuple(role for role, _ in roles[discogs_id].most_common(3)),
            tuple(sorted(albums[discogs_id])),
            -discogs_id if discogs_id in musicians else None,
        )
        for discogs_id in names
    ]
    return sorted(people, key=lambda p: (-len(p.album_ids), sort_name(p.name)))


def artist_figures(store: JsonStore, artist_id: int) -> ArtistFigures:
    """What the collection says about one artist.

    Args:
        store: The store of the collection.
        artist_id: The artist.

    Returns:
        Its figures.
    """
    artists = store.load(Artist)
    albums = store.load(Album)
    artist = next(a for a in artists if a.id == artist_id)
    own = [album for album in albums if album.artist_id == artist_id]
    releases = store.load(ReleaseEnrichment)
    by_did = artists_by_discogs_id(artists)

    counts = Counter(album.artist_id for album in albums)
    various = {a.id for a in artists if is_various(a)}
    others = [count for other, count in counts.items() if other not in various]
    mine = counts[artist_id]
    rank = None if artist_id in various or not mine else 1 + sum(count > mine for count in others)

    shelf_of = {p.album_id: p.shelf_id for p in store.load(Placement)}
    base = load_settings(store.data_dir).width_constants.base_per_disc
    placed = [album for album in own if album.id in shelf_of]

    style_names = {style.id: style.name for style in store.load(Style)}
    styles = Counter(style_names[i] for album in own for i in set(album.style_ids) if i in style_names)

    per_year = Counter(album.original_release_year for album in own if album.original_release_year)
    years = (
        tuple((year, per_year[year]) for year in range(min(per_year), max(per_year) + 1)) if per_year else ()
    )

    credits = credits_by_release(releases)
    entries = [
        (album.id, credit.discogs_artist_id, credit.name, parts)
        for album in own
        if artist_id not in various
        for credit in credits.get(album.release_id, ())
        if credit.discogs_artist_id != artist.discogs_artist_id and not named_in(credit.name, artist.name)
        for parts in [on_the_record(credit.role)]
        if parts
    ]
    records = store.load(ArtistEnrichment)
    musicians = musicians_as_points(side_players(artists, albums, records, releases), artists)
    companions = [p for p in _people(entries, by_did, musicians) if len(p.album_ids) >= COMPANION_ALBUMS][:COMPANIONS]
    return ArtistFigures(
        albums=mine,
        rank=rank,
        rank_shared=rank is not None and sum(count == mine for count in others) > 1,
        width_cm=sum(album.width_cm or base for album in placed),
        shelves=len({shelf_of[album.id] for album in placed}),
        styles=tuple(sorted(styles.items(), key=lambda item: (-item[1], item[0].casefold()))),
        years=years,
        companions=tuple(companions),
        appears_on=tuple(
            entry for entry in credited_on_albums(artists, albums, releases) if entry.artist_id == artist_id
        ),
    )


def _minutes(tracks) -> int | None:
    """How long the songs last together; None unless Discogs gives the length of every one."""
    seconds = 0
    for track in tracks:
        parts = (track.duration or "").split(":")
        if len(parts) not in (2, 3) or not all(part.isdigit() for part in parts):
            return None
        seconds += sum(int(part) * 60 ** (len(parts) - 1 - index) for index, part in enumerate(parts))
    return round(seconds / 60) if tracks else None


def album_figures(store: JsonStore, album_id: int) -> AlbumFigures:
    """What the collection says about one album.

    Args:
        store: The store of the collection.
        album_id: The album.

    Returns:
        Its figures.
    """
    artists = store.load(Artist)
    albums = store.load(Album)
    album = next(a for a in albums if a.id == album_id)
    names = {a.id: a.name for a in artists}
    artist = next((a for a in artists if a.id == album.artist_id), None)
    releases = store.load(ReleaseEnrichment)
    release = next((r for r in releases if r.release_id == album.release_id), None)
    by_did = artists_by_discogs_id(artists)

    # The artist's albums by year; a compilation's "Various" has no such order.
    dated = sorted(
        (a for a in albums if a.artist_id == album.artist_id and a.original_release_year),
        key=lambda a: (a.original_release_year, a.title.casefold()),
    )
    ordered = album.original_release_year and artist is not None and not is_various(artist)
    place = dated.index(album) if ordered else None

    same_year = sorted(
        (a for a in albums if album.original_release_year and a.original_release_year == album.original_release_year and a.id != album_id),
        key=lambda a: (sort_name(names.get(a.artist_id, "")), a.title.casefold()),
    )

    style_names = {style.id: style.name for style in store.load(Style)}
    per_style = Counter(i for a in albums for i in set(a.style_ids))
    styles = sorted(
        ((style_names[i], per_style[i]) for i in set(album.style_ids) if i in style_names),
        key=lambda item: (-item[1], item[0].casefold()),
    )

    on_release: dict[int, list[Album]] = {}
    for other in albums:
        on_release.setdefault(other.release_id, []).append(other)

    per_label: Counter[int] = Counter()
    for other in releases:
        for label_id in {label.discogs_label_id for label in other.labels or ()}:
            per_label[label_id] += len(on_release.get(other.release_id, ()))
    labels = {
        label.discogs_label_id: (plain_name(label.name), per_label[label.discogs_label_id], label.catalogue_number)
        for label in (release.labels or () if release else ())
        if not label.name.casefold().startswith(NO_LABEL)
    }

    # Everyone on the record of any album, and an artist's own albums count for them too.
    on_albums: dict[int, set[int]] = {}
    for other in releases:
        credited = {c.discogs_artist_id for c in other.credits or () if c.discogs_artist_id and on_the_record(c.role)}
        for discogs_id in credited:
            on_albums.setdefault(discogs_id, set()).update(a.id for a in on_release.get(other.release_id, ()))
    discogs_id_of = {a.id: a.discogs_artist_id for a in artists if a.discogs_artist_id is not None}
    for other in albums:
        if other.artist_id in discogs_id_of:
            on_albums.setdefault(discogs_id_of[other.artist_id], set()).add(other.id)

    names_here: dict[int, str] = {}
    roles: dict[int, dict[str, None]] = {}
    for credit in release.credits or () if release else ():
        parts = on_the_record(credit.role)
        if not parts or not credit.discogs_artist_id or artist is None:
            continue
        if credit.discogs_artist_id == artist.discogs_artist_id or named_in(credit.name, artist.name):
            continue
        names_here.setdefault(credit.discogs_artist_id, plain_name(credit.name))
        roles.setdefault(credit.discogs_artist_id, {}).update(dict.fromkeys(parts))
    musicians = (
        musicians_as_points(side_players(artists, albums, store.load(ArtistEnrichment), releases), artists)
        if names_here and store.exists(ArtistEnrichment)
        else set()
    )
    people = sorted(
        (
            Person(
                name,
                by_did[discogs_id].id if discogs_id in by_did else None,
                tuple(roles[discogs_id]),
                tuple(sorted(on_albums.get(discogs_id, {album_id}))),
                -discogs_id if discogs_id in musicians else None,
            )
            for discogs_id, name in names_here.items()
        ),
        key=lambda p: (-len(p.album_ids), sort_name(p.name)),
    )

    shared: dict[int, list[str]] = {}
    for person in people:
        for other_id in person.album_ids:
            if other_id != album_id:
                shared.setdefault(other_id, []).append(person.name)
    alike = sorted(
        ((other_id, tuple(together)) for other_id, together in shared.items() if len(together) >= ALIKE_PEOPLE),
        key=lambda item: (-len(item[1]), item[0]),
    )[:ALIKE_ALBUMS]

    tracks = (release.tracklist or ()) if release else ()
    credit_names = {c.discogs_artist_id: plain_name(c.name) for c in (release.credits or () if release else ())}
    per_writer = Counter(writer for track in tracks for writer in set(track.writers or ()))
    writers = sorted(
        ((credit_names[writer], count) for writer, count in per_writer.items() if writer in credit_names),
        key=lambda item: (-item[1], sort_name(item[0])),
    )
    return AlbumFigures(
        tracks=len(tracks),
        minutes=_minutes(tracks),
        writers=tuple(writers),
        position=place + 1 if place is not None else None,
        of_artist=len(dated),
        earlier=dated[place - 1].id if place else None,
        later=dated[place + 1].id if place is not None and place + 1 < len(dated) else None,
        same_year=tuple(a.id for a in same_year),
        styles=tuple(styles),
        labels=tuple(sorted(labels.values(), key=lambda item: (-item[1], item[0].casefold()))),
        people=tuple(people),
        alike=tuple(alike),
        songs_elsewhere=len(album_songs_elsewhere(store, album_id)),
    )


def collection_figures(store: JsonStore) -> CollectionFigures:
    """Who and what recurs across the collection.

    Args:
        store: The store of the collection.

    Returns:
        The figures.
    """
    artists = store.load(Artist)
    albums = store.load(Album)
    releases = store.load(ReleaseEnrichment)
    by_did = artists_by_discogs_id(artists)
    by_release = {release.release_id: release for release in releases}

    players = side_players(artists, albums, store.load(ArtistEnrichment), releases)
    musicians = musicians_as_points(players, artists)
    entries = [(p.album_id, p.discogs_id, p.name, p.roles) for p in players]

    songs = []
    for _, heard in collection_songs(artists, albums, releases):
        having = {h.artist_id for h in heard}
        if len(having) > 1:
            title = Counter(h.title for h in heard).most_common(1)[0][0]
            songs.append(RecordedSong(title, len(having), tuple(sorted({h.album_id for h in heard}))))
    songs.sort(key=lambda s: (-s.artists, -len(s.album_ids), sort_name(s.title)))

    names: dict[int, str] = {}
    on_label: dict[int, set[int]] = {}
    for album in albums:
        release = by_release.get(album.release_id)
        for label in (release.labels or ()) if release else ():
            if not label.name.casefold().startswith(NO_LABEL):
                names.setdefault(label.discogs_label_id, label.name)
                on_label.setdefault(label.discogs_label_id, set()).add(album.id)
    labels = sorted(
        (CountedLabel(names[i], tuple(sorted(found))) for i, found in on_label.items()),
        key=lambda label: (-len(label.album_ids), sort_name(label.name)),
    )
    shown = network(store)
    per_decade = Counter(a.original_release_year // 10 * 10 for a in albums if a.original_release_year)
    decades = (
        tuple((decade, per_decade[decade]) for decade in range(min(per_decade), max(per_decade) + 1, 10))
        if per_decade
        else ()
    )
    return CollectionFigures(
        sidemen=tuple(_people(entries, by_did, musicians)[:TOP]),
        songs=tuple(songs[:TOP]),
        labels=tuple(labels[:TOP]),
        hubs=_hubs(shown),
        longest_way=_longest_way(shown),
        decades=decades,
        without_year=sum(not album.original_release_year for album in albums),
        clusters=_clusters(store, albums),
        credits_fetched=any(release.credits is not None for release in releases),
        labels_fetched=any(release.labels is not None for release in releases),
    )


def _close_ties(shown: Network) -> dict[int, set[int]]:
    """Per artist the artists it has a close tie with.

    That is anything but a shared song or label, and no musician without an album.
    """
    next_to: dict[int, set[int]] = {}
    for link in shown.links:
        # Among artists: a musician without an album is not one of those holding things together.
        if link.one > 0 and not LOOSE_TIES.issuperset(link.ties):
            next_to.setdefault(link.one, set()).add(link.other)
            next_to.setdefault(link.other, set()).add(link.one)
    return next_to


def _hubs(shown: Network) -> tuple[Hub, ...]:
    """The artists with the most close ties."""
    names = {point.artist_id: point.name for point in shown.points}
    next_to = _close_ties(shown)
    most = sorted(next_to, key=lambda artist_id: (-len(next_to[artist_id]), sort_name(names[artist_id])))
    return tuple(Hub(artist_id, names[artist_id], len(next_to[artist_id])) for artist_id in most[:HUBS])


def _longest_way(shown: Network) -> LongestWay | None:
    """The two artists furthest apart along close ties.

    Songs and labels are left out: they tie nearly everyone to everyone in a few steps.
    """
    names = {point.artist_id: point.name for point in shown.points}
    sorted_as = {artist_id: sort_name(name) for artist_id, name in names.items()}
    next_to = _close_ties(shown)
    best: tuple[int, str, str, int, int] | None = None
    for start in next_to:
        steps = {start: 0}
        queue = deque([start])
        while queue:
            here = queue.popleft()
            for other in next_to[here]:
                if other not in steps:
                    steps[other] = steps[here] + 1
                    queue.append(other)
        for end, distance in steps.items():
            one, other = sorted((start, end), key=sorted_as.__getitem__)
            found = (-distance, sorted_as[one], sorted_as[other], one, other)
            if distance and (best is None or found < best):
                best = found
    if best is None:
        return None
    return LongestWay(best[3], names[best[3]], best[4], names[best[4]], -best[0])


def _clusters(store: JsonStore, albums: list[Album]) -> tuple[CountedCluster, ...]:
    cluster_of = {a.artist_id: a.cluster_id for a in store.load(ArtistClusterAssignment)}
    names = {cluster.id: cluster.name for cluster in store.load(Cluster)}
    counts = Counter(cluster_of.get(album.artist_id) for album in albums)
    return tuple(
        CountedCluster(cluster_id, names.get(cluster_id), count)
        for cluster_id, count in sorted(counts.items(), key=lambda item: (item[0] is None, -item[1], names.get(item[0], "")))
    )


def from_the_shelf(store: JsonStore, day: date, turn: int = 0) -> tuple[int | None, tuple[int, ...]]:
    """Something to pull from the shelf.

    Args:
        store: The store of the collection.
        day: The day it is chosen for: the same all day.
        turn: Asks for another one that day.

    Returns:
        An album that stands somewhere, if any, and those from this year, long ago, as album ids.
    """
    placed = sorted({p.album_id for p in store.load(Placement)})
    chance = random.Random(f"{day.isoformat()}/{turn}")  # noqa: S311 - picks a record, not a secret
    pick = chance.choice(placed) if placed else None
    year = day.year - LONG_AGO_YEARS
    then = sorted(album.id for album in store.load(Album) if album.original_release_year == year)
    return pick, tuple(sorted(chance.sample(then, min(LONG_AGO_ALBUMS, len(then)))))
