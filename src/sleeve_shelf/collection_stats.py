"""Application service for the figures on an artist's page and the Statistics screen: what the
collection says about one artist, and who and what recurs across all of it."""

import random
import re
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
    in_order,
)
from sleeve_shelf.network import (
    LOOSE_TIES,
    NO_LABEL,
    Network,
    OnRecord,
    collection_songs,
    credited_on_albums,
    is_various,
    musicians_as_points,
    named_in,
    network,
    on_the_record,
    plain_name,
    side_players,
)
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.sorting.families import sort_name

# Someone on at least this many of an artist's albums is one it keeps recording with.
COMPANION_ALBUMS = 2
COMPANIONS = 6
# How many a list on the Statistics screen holds.
TOP = 20

# How many artists the list of the most connected holds.
HUBS = 10
# How many albums "from this year, long ago" shows, and how long ago that is.
LONG_AGO_ALBUMS = 6
LONG_AGO_YEARS = 50


@dataclass(frozen=True, slots=True)
class Person:
    """Someone credited across albums; artist_id when the person is an artist in the collection,
    point_id when a musician with a point of their own in the network."""

    name: str
    artist_id: int | None
    roles: tuple[str, ...]
    album_ids: tuple[int, ...]
    point_id: int | None = None


@dataclass(frozen=True, slots=True)
class ArtistFigures:
    albums: int
    # The artist's place among those with the most albums; None for a compilation's "Various".
    rank: int | None
    rank_shared: bool
    # What stands on a shelf: how much room it takes, and on how many shelves.
    width_cm: float
    shelves: int
    # Albums per style, the most first: an album can have several.
    styles: tuple[tuple[str, int], ...]
    # Albums per original year, every year from the first to the last.
    years: tuple[tuple[int, int], ...]
    companions: tuple[Person, ...]
    # Albums of others the artist is on.
    appears_on: tuple[OnRecord, ...]


@dataclass(frozen=True, slots=True)
class RecordedSong:
    title: str
    artists: int
    album_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CountedLabel:
    name: str
    album_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Hub:
    """An artist with its number of close ties: anything but a shared song or label."""

    artist_id: int
    name: str
    ties: int


@dataclass(frozen=True, slots=True)
class LongestWay:
    """The two artists furthest apart along close ties, of those a way leads between."""

    one: int
    one_name: str
    other: int
    other_name: str
    steps: int


@dataclass(frozen=True, slots=True)
class CountedCluster:
    # None for the albums of artists without a cluster.
    cluster_id: int | None
    name: str | None
    albums: int


@dataclass(frozen=True, slots=True)
class CollectionFigures:
    sidemen: tuple[Person, ...]
    songs: tuple[RecordedSong, ...]
    labels: tuple[CountedLabel, ...]
    hubs: tuple[Hub, ...]
    longest_way: LongestWay | None
    # Albums per decade, every decade from the first to the last, and those without a year.
    decades: tuple[tuple[int, int], ...]
    without_year: int
    # Albums per cluster, the most first.
    clusters: tuple[CountedCluster, ...]
    # Whether the fetch run has brought them yet, for all or part of the collection.
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
    """What the collection says about one artist."""
    artists = store.load(Artist)
    albums = store.load(Album)
    artist = next(a for a in artists if a.id == artist_id)
    own = [album for album in albums if album.artist_id == artist_id]
    releases = store.load(ReleaseEnrichment)
    by_did = {a.discogs_artist_id: a for a in artists if a.discogs_artist_id is not None}

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

    credits = {release.release_id: release.credits or () for release in releases}
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


def collection_figures(store: JsonStore) -> CollectionFigures:
    """Who and what recurs across the collection."""
    artists = store.load(Artist)
    albums = store.load(Album)
    releases = store.load(ReleaseEnrichment)
    by_id = {a.id: a for a in artists}
    by_did = {a.discogs_artist_id: a for a in artists if a.discogs_artist_id is not None}
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
    """Per artist the artists it has a close tie with: anything but a shared song or label, and
    no musician without an album."""
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
    """The two artists furthest apart along close ties. Songs and labels are left out: they tie
    nearly everyone to everyone in a few steps."""
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
    """Something to pull from the shelf: an album that stands somewhere, the same all day unless
    another is asked for (turn), and those from this year, long ago. Album ids."""
    placed = sorted({p.album_id for p in store.load(Placement)})
    chance = random.Random(f"{day.isoformat()}/{turn}")  # noqa: S311 - picks a record, not a secret
    pick = chance.choice(placed) if placed else None
    year = day.year - LONG_AGO_YEARS
    then = sorted(album.id for album in store.load(Album) if album.original_release_year == year)
    return pick, tuple(sorted(chance.sample(then, min(LONG_AGO_ALBUMS, len(then)))))
