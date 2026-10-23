"""Application service for the Move screen: an album, an artist, a family or a cluster moved to
a shelf, or to where it belongs, worked out as a plan to look at before it is carried out."""

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

from sleeve_shelf.domain import (
    Album,
    AliasGroup,
    Artist,
    Cabinet,
    Cluster,
    Placement,
    PlacementSource,
    Shelf,
    WidthConstants,
    find_by_id,
    in_order,
)
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.placing import ShelvesChanged
from sleeve_shelf.proposal import sort_collection
from sleeve_shelf.sorting.families import sort_name
from sleeve_shelf.sorting.placement import TOLERANCE_CM, fill_shelves
from sleeve_shelf.spots import belonging
from sleeve_shelf.taking_part import kept_shelf_ids, usable_shelves
from sleeve_shelf.versions import save_if_unsaved

# The target that takes albums off their shelf.
OFF_SHELF = 0


class Kind(StrEnum):
    """What is moved."""

    ALBUM = "album"
    ARTIST = "artist"
    FAMILY = "family"
    CLUSTER = "cluster"


class How(StrEnum):
    """Where on the shelves it goes."""

    # At the start of a shelf, running on over the next shelves of its cabinet; what stood
    # there moves up behind it.
    FRONT = "front"
    # At the end of a shelf, after what stands there.
    END = "end"
    # Next to what each album belongs with, as the shelves stand: no shelf to choose.
    BELONGS = "belongs"


@dataclass(frozen=True, slots=True)
class Selection:
    """What is moved, with its albums in the order a sorting gives them."""

    kind: Kind
    id: int
    name: str
    album_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ShelfChange:
    """A shelf whose contents a move changes."""

    shelf_id: int
    cabinet_id: int
    name: str
    before: int
    after: int
    filled_cm: float
    width_cm: float | None
    width_measured: bool

    @property
    def over(self) -> bool:
        return bool(self.width_cm) and self.filled_cm > self.width_cm + TOLERANCE_CM


@dataclass(frozen=True, slots=True)
class Plan:
    """What a move would do; nothing has changed yet."""

    selection: Selection
    how: How
    shelf_id: int | None
    # The albums that go somewhere else.
    moved: tuple[int, ...]
    # Where it belongs: albums that have no such place stay where they are.
    without_spot: tuple[int, ...]
    changes: tuple[ShelfChange, ...]
    placements: tuple[Placement, ...]


def _sorted_on_shelves(store: JsonStore) -> list[tuple[int, int, int | None, int | None]]:
    """The albums that stand on a shelf a proposal fills, as (album, artist, family, cluster),
    in the order a proposal sorts them: by cluster, era band, artist (a family together),
    year. What stands in a showcase or a cabinet kept outside the sorting is left out."""
    kept = kept_shelf_ids(store)
    shelf_of = {p.album_id: p.shelf_id for p in store.load(Placement)}
    family_of = {artist.id: artist.alias_group_id for artist in store.load(Artist)}
    result = sort_collection(store)
    return [
        (
            entry.album_id,
            result.albums[entry.album_id].artist_id,
            family_of.get(result.albums[entry.album_id].artist_id),
            entry.cluster_id,
        )
        for entry in result.ordered
        if entry.album_id in shelf_of and shelf_of[entry.album_id] not in kept
    ]


def selection(store: JsonStore, kind: Kind, item_id: int) -> Selection | None:
    """The album, artist, family or cluster with this id, and the albums that would move.

    An album moves whatever it stands on. Of an artist, family or cluster the albums that
    stand on a shelf move, in sorting order; what stands in a showcase or a cabinet kept
    outside the sorting stays there, and albums without a place stay without one.
    """
    if kind is Kind.ALBUM:
        album = find_by_id(store.load(Album), item_id)
        if album is None:
            return None
        artist = find_by_id(store.load(Artist), album.artist_id)
        name = f"{artist.name} — {album.title}" if artist else album.title
        return Selection(kind, item_id, name, (item_id,))
    names = {
        Kind.ARTIST: {artist.id: artist.name for artist in store.load(Artist)},
        Kind.FAMILY: {group.id: group.label for group in store.load(AliasGroup)},
        Kind.CLUSTER: {cluster.id: cluster.name for cluster in store.load(Cluster)},
    }[kind]
    if item_id not in names:
        return None
    column = {Kind.ARTIST: 1, Kind.FAMILY: 2, Kind.CLUSTER: 3}[kind]
    albums = tuple(row[0] for row in _sorted_on_shelves(store) if row[column] == item_id)
    return Selection(kind, item_id, names[item_id], albums)


def find(store: JsonStore, text: str, limit: int = 8) -> list[tuple[Kind, int, str, int]]:
    """Clusters, families, artists and albums whose name holds every word of the text, as
    (kind, id, name, number of albums that would move), the broadest first."""
    words = sort_name(text).split()
    if not words:
        return []

    def matches(name: str) -> bool:
        name = sort_name(name)
        return all(word in name for word in words)

    artists = {artist.id: artist.name for artist in store.load(Artist)}
    found: list[tuple[Kind, int, str, int]] = []
    # How many albums each would move, from one sorting of the collection for all of them.
    on_shelves = _sorted_on_shelves(store)
    counts = {
        kind: Counter(row[column] for row in on_shelves)
        for kind, column in ((Kind.ARTIST, 1), (Kind.FAMILY, 2), (Kind.CLUSTER, 3))
    }
    for kind, items in (
        (Kind.CLUSTER, [(c.id, c.name) for c in store.load(Cluster)]),
        (Kind.FAMILY, [(g.id, g.label) for g in store.load(AliasGroup)]),
        (Kind.ARTIST, list(artists.items())),
        (Kind.ALBUM, [(a.id, f"{artists.get(a.artist_id, '')} — {a.title}") for a in store.load(Album)]),
    ):
        hits = sorted((name.casefold(), item_id, name) for item_id, name in items if matches(name))
        found += [
            (kind, item_id, name, 1 if kind is Kind.ALBUM else counts[kind][item_id])
            for _, item_id, name in hits[:limit]
        ]
    return found


def plan(
    store: JsonStore, chosen: Selection, how: How, shelf_id: int | None, constants: WidthConstants
) -> Plan:
    """Work out what moving the selection would do, without changing anything.

    At the start of a shelf a proposal fills, the albums run on over the next shelves of
    its cabinet and what stood there moves up behind them, by width; what no longer fits
    stays at the end of the cabinet's last shelf. At the start of another shelf (a showcase,
    a shelf without a width) they are simply put in front. At the end of a shelf they come
    after what stands there. OFF_SHELF takes them off their shelf. Where it belongs puts
    each album next to what it belongs with, as the shelves stand; an album without such a
    place stays where it is. Nothing drops off a shelf.
    """
    shelves = store.load(Shelf)
    by_id = {shelf.id: shelf for shelf in shelves}
    if how is not How.BELONGS and shelf_id != OFF_SHELF and shelf_id not in by_id:
        raise ShelvesChanged
    placements = store.load(Placement)
    rows: dict[int, list[int]] = {}
    for p in sorted(placements, key=lambda p: (p.shelf_id, p.position)):
        rows.setdefault(p.shelf_id, []).append(p.album_id)
    moving = list(chosen.album_ids)
    without_spot: list[int] = []
    if how is How.BELONGS:
        others = [p for p in placements if p.album_id not in set(moving)]
        # Where they stand now is what is being changed, so it says nothing about their order.
        spots = belonging(store, moving, others, sort_collection(store, set(moving)))
        without_spot = [album_id for album_id in moving if album_id not in spots]
        moving = [album_id for album_id in moving if album_id in spots]
    leaving = set(moving)
    new_rows = {shelf: [a for a in row if a not in leaving] for shelf, row in rows.items()}
    albums = {album.id: album for album in store.load(Album)}

    def width(album_id: int) -> float:
        album = albums.get(album_id)
        return (album.width_cm if album else None) or constants.base_per_disc

    if how is How.BELONGS:
        # Albums that go to the same place stand there together, in sorting order.
        for album_id in moving:
            spot = spots[album_id]
            row = new_rows.setdefault(spot.shelf_id, [])
            if spot.after_album_id is not None and spot.after_album_id in row:
                index = row.index(spot.after_album_id) + 1
                while index < len(row) and row[index] in leaving and _placed_before(row[index], album_id, moving):
                    index += 1
            elif spot.before_album_id is not None and spot.before_album_id in row:
                index = row.index(spot.before_album_id)
            else:
                index = len(row)
            row.insert(index, album_id)
    elif shelf_id == OFF_SHELF:
        pass
    elif how is How.END:
        new_rows.setdefault(shelf_id, []).extend(moving)
    else:
        usable = usable_shelves(store)[0]
        start = by_id[shelf_id]
        if start in usable:
            in_cabinet = [shelf for shelf in usable if shelf.cabinet_id == start.cabinet_id]
            chain = in_cabinet[in_cabinet.index(start):]
            row = moving + [a for shelf in chain for a in new_rows.get(shelf.id, [])]
            # A shelf holds at least what stands on it now, whatever its width says: a width
            # from the workbook is an estimate that comes out too narrow, and filling by it
            # alone would pile what no longer "fits" onto the cabinet's last shelf.
            room = {
                shelf.id: max(shelf.width_cm, sum(width(a) for a in rows.get(shelf.id, [])))
                for shelf in chain
            }
            spots, left_out = fill_shelves(
                [(album_id, width(album_id)) for album_id in row],
                [(shelf.id, room[shelf.id]) for shelf in chain],
            )
            for shelf in chain:
                new_rows[shelf.id] = []
            for spot in sorted(spots, key=lambda s: s.position):
                new_rows[spot.shelf_id].append(spot.album_id)
            # Nothing drops off: what no longer fits stays at the end of the cabinet.
            new_rows[chain[-1].id].extend(left_out)
        else:
            new_rows[shelf_id] = moving + new_rows.get(shelf_id, [])

    return _plan(store, chosen, how, shelf_id, rows, new_rows, moving, without_spot, placements, width)


def _placed_before(standing: int, album_id: int, moving: list[int]) -> bool:
    return moving.index(standing) < moving.index(album_id)


def _plan(store, chosen, how, shelf_id, rows, new_rows, moving, without_spot, placements, width) -> Plan:
    source = {p.album_id: p.source for p in placements}
    shelves = store.load(Shelf)
    cabinets = {cabinet.id: cabinet for cabinet in store.load(Cabinet)}
    walked = [
        shelf
        for cabinet in in_order(list(cabinets.values()))
        for shelf in in_order([s for s in shelves if s.cabinet_id == cabinet.id])
    ]
    changed = [shelf for shelf in walked if rows.get(shelf.id, []) != new_rows.get(shelf.id, [])]
    leaving = set(moving)
    kept = [p for p in placements if p.shelf_id not in {shelf.id for shelf in changed}]
    rebuilt = [
        Placement(
            album_id,
            shelf.id,
            position,
            PlacementSource.MANUAL if album_id in leaving else source.get(album_id, PlacementSource.MANUAL),
        )
        for shelf in changed
        for position, album_id in enumerate(new_rows.get(shelf.id, []))
    ]
    return Plan(
        chosen,
        how,
        shelf_id,
        tuple(moving),
        tuple(without_spot),
        tuple(
            ShelfChange(
                shelf.id,
                shelf.cabinet_id,
                f"{cabinets[shelf.cabinet_id].name} › {shelf.name}",
                len(rows.get(shelf.id, [])),
                len(new_rows.get(shelf.id, [])),
                sum(width(album_id) for album_id in new_rows.get(shelf.id, [])),
                shelf.width_cm,
                shelf.width_measured,
            )
            for shelf in changed
        ),
        tuple(kept + rebuilt),
    )


def carry_out(store: JsonStore, chosen: Plan) -> None:
    """Make the planned move: the layout as it was is kept as a version first."""
    if not chosen.changes:
        return
    save_if_unsaved(store, "before moving")
    store.save(Placement, list(chosen.placements))
