"""Application service for the figures on an artist's page and the Statistics screen: what the
collection says about one artist, and who and what recurs across all of it."""

import re
from collections import Counter
from dataclasses import dataclass

from sleeve_shelf.config import load_settings
from sleeve_shelf.domain import Album, Artist, Placement, ReleaseEnrichment, Style
from sleeve_shelf.network import OnRecord, collection_songs, credited_on_albums, is_various, on_the_record
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.sorting.families import sort_name

# Someone on at least this many of an artist's albums is one it keeps recording with.
COMPANION_ALBUMS = 2
COMPANIONS = 6
# How many a list on the Statistics screen holds.
TOP = 20

_PRODUCER = re.compile(r"produc", re.IGNORECASE)
# Discogs' own entry for what came out without a label.
_NO_LABEL = "not on label"


@dataclass(frozen=True, slots=True)
class Person:
    """Someone credited across albums; artist_id when the person is an artist in the collection."""

    name: str
    artist_id: int | None
    roles: tuple[str, ...]
    album_ids: tuple[int, ...]


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
class CollectionFigures:
    sidemen: tuple[Person, ...]
    songs: tuple[RecordedSong, ...]
    labels: tuple[CountedLabel, ...]
    # Whether the fetch run has brought them yet, for all or part of the collection.
    credits_fetched: bool
    labels_fetched: bool


def _named_in(name: str, album_artist: str) -> bool:
    """Whether the credited person is named on the record itself: Nick Cave on an album of
    Nick Cave & The Bad Seeds is no sideman."""
    found = sort_name(name)
    return bool(found) and re.search(r"(?<!\w)" + re.escape(found) + r"(?!\w)", sort_name(album_artist)) is not None


def _people(
    entries: list[tuple[int, int, str, tuple[str, ...]]], by_did: dict[int, Artist]
) -> list[Person]:
    """People from (album, Discogs id, name, roles), those on the most albums first."""
    names: dict[int, str] = {}
    albums: dict[int, set[int]] = {}
    roles: dict[int, Counter[str]] = {}
    for album_id, discogs_id, name, parts in entries:
        # Without Discogs' "(3)", which tells apart people of one name on Discogs only.
        names.setdefault(discogs_id, re.sub(r"\s*\(\d+\)$", "", name))
        albums.setdefault(discogs_id, set()).add(album_id)
        roles.setdefault(discogs_id, Counter()).update(parts)
    people = [
        Person(
            names[discogs_id],
            by_did[discogs_id].id if discogs_id in by_did else None,
            tuple(role for role, _ in roles[discogs_id].most_common(3)),
            tuple(sorted(albums[discogs_id])),
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
        if credit.discogs_artist_id != artist.discogs_artist_id and not _named_in(credit.name, artist.name)
        for parts in [on_the_record(credit.role)]
        if parts
    ]
    companions = [p for p in _people(entries, by_did) if len(p.album_ids) >= COMPANION_ALBUMS][:COMPANIONS]
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

    entries = []
    for album in albums:
        release = by_release.get(album.release_id)
        owner = by_id.get(album.artist_id)
        if release is None or owner is None or is_various(owner):
            continue
        for credit in release.credits or ():
            if credit.discogs_artist_id == owner.discogs_artist_id or _named_in(credit.name, owner.name):
                continue
            # Who plays and sings on the records: a producer is not at the instrument.
            parts = tuple(part for part in on_the_record(credit.role) if not _PRODUCER.search(part))
            if parts:
                entries.append((album.id, credit.discogs_artist_id, credit.name, parts))

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
            if not label.name.casefold().startswith(_NO_LABEL):
                names.setdefault(label.discogs_label_id, label.name)
                on_label.setdefault(label.discogs_label_id, set()).add(album.id)
    labels = sorted(
        (CountedLabel(names[i], tuple(sorted(found))) for i, found in on_label.items()),
        key=lambda label: (-len(label.album_ids), sort_name(label.name)),
    )
    return CollectionFigures(
        sidemen=tuple(_people(entries, by_did)[:TOP]),
        songs=tuple(songs[:TOP]),
        labels=tuple(labels[:TOP]),
        credits_fetched=any(release.credits is not None for release in releases),
        labels_fetched=any(release.labels is not None for release in releases),
    )
