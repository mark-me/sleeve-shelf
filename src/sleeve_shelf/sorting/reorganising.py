"""Carrying out a new layout on the real shelves, a table full at a time.

The plan is worked out from the shelves as they stand, what lies on the table and what was set
aside, towards the layout the reorganisation takes them to. It is a heuristic, not the shortest
plan there is (decided by Mark 2026-11-10): an album that already stands on its shelf, in the
right order among the others that stay, is not touched; the rest passes over the table. An album
is taken out only when it can go somewhere: first those whose new shelf has room now, else those
that make room on a shelf the table is waiting for. When nothing fits anywhere, the albums on the
table are set aside — a crate, an empty shelf — and taken back once there is room.

A step is one thing done at a cabinet: taking albums out of one shelf, putting albums on one
shelf after a named album, setting albums aside, or leaving out what has no place in the new
layout. Steps form rounds that each end with an empty table, the points to stop and go on another
day.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from sleeve_shelf.sorting.placement import TOLERANCE_CM


class StepKind(StrEnum):
    """What a step does."""

    # Out of a shelf onto the table; without a shelf, from the albums that have no place.
    TAKE = "take"
    # From where they were set aside, back onto the table.
    TAKE_BACK = "take_back"
    # From the table onto a shelf, after a named album or at the front.
    PUT = "put"
    # From the table somewhere else for now: the table is not enough.
    SET_ASIDE = "set_aside"
    # From the table: no place in the new layout, so without a place from now on.
    LEAVE_OUT = "leave_out"


@dataclass(frozen=True)
class Step:
    """One thing done at a cabinet.

    Attributes:
        kind: What it does.
        album_ids: The albums, in the order they stand or go.
        shelf_id: The shelf taken from or put on; None for the albums without a place, the
            albums set aside and those left out.
        after_album_id: For putting: the album they go after; None at the front of the shelf.
    """

    kind: StepKind
    album_ids: tuple[int, ...]
    shelf_id: int | None = None
    after_album_id: int | None = None


@dataclass(frozen=True)
class Situation:
    """Where things are, and where they go.

    Attributes:
        rows: The albums on each shelf taking part, in the order they stand.
        target: The albums each shelf holds in the new layout, in their order.
        left_out: Albums the new layout has no place for.
        table: The albums on the table now.
        aside: The albums set aside now.
        widths: The width of each album, in cm.
        room: The width of each shelf, in cm.
        table_size: How many records may be out at once.
        taken: How many albums were taken out already in the round at hand.
    """

    rows: dict[int, list[int]]
    target: dict[int, list[int]]
    left_out: frozenset[int] = frozenset()
    table: tuple[int, ...] = ()
    aside: tuple[int, ...] = ()
    widths: dict[int, float] = field(default_factory=dict)
    room: dict[int, float] = field(default_factory=dict)
    table_size: int = 50
    taken: int = 0


def to_move(situation: Situation) -> set[int]:
    """The albums still to pass over the table: all but those that stay where they stand.

    Args:
        situation: Where things are, and where they go.

    Returns:
        The albums.
    """
    goes_to = _goes_to(situation)
    stay = _staying(situation.rows, situation.target, goes_to)
    on_shelves = {album for row in situation.rows.values() for album in row}
    moving = {album for album in on_shelves if album in goes_to and album not in stay}
    moving |= {album for album in on_shelves if album in situation.left_out}
    # Albums without a place that the new layout puts on a shelf.
    nowhere = set(goes_to) - on_shelves - set(situation.table) - set(situation.aside)
    return moving | nowhere | set(situation.table) | set(situation.aside)


def plan(situation: Situation) -> list[list[Step]]:
    """The rounds of steps that take the shelves to the new layout.

    Args:
        situation: Where things are, and where they go.

    Returns:
        The rounds, each a list of steps ending with an empty table; none when nothing is left.
    """
    return _Planner(situation).run()


def _goes_to(situation: Situation) -> dict[int, tuple[int, int]]:
    """Per album that has a shelf in the new layout: that shelf and its place in the row."""
    return {
        album: (shelf, index)
        for shelf, row in situation.target.items()
        for index, album in enumerate(row)
    }


def _staying(
    rows: dict[int, list[int]], target: dict[int, list[int]], goes_to: dict[int, tuple[int, int]]
) -> set[int]:
    """The albums that stay where they stand: on their new shelf, in the longest run in order."""
    stay: set[int] = set()
    for shelf, row in rows.items():
        here = [album for album in row if goes_to.get(album, (None, 0))[0] == shelf]
        stay |= _longest_in_order(here, [goes_to[album][1] for album in here])
    return stay


def _longest_in_order(albums: list[int], ranks: list[int]) -> set[int]:
    """The most albums that are already in the order of their ranks (a longest increasing run)."""
    tails: list[int] = []  # the index into albums ending the best run of each length
    before = [-1] * len(albums)
    for index, rank in enumerate(ranks):
        low, high = 0, len(tails)
        while low < high:
            middle = (low + high) // 2
            if ranks[tails[middle]] < rank:
                low = middle + 1
            else:
                high = middle
        before[index] = tails[low - 1] if low else -1
        if low == len(tails):
            tails.append(index)
        else:
            tails[low] = index
    kept, index = set(), tails[-1] if tails else -1
    while index >= 0:
        kept.add(albums[index])
        index = before[index]
    return kept


NOWHERE = "nowhere"
ASIDE = "aside"


class _Planner:
    """Works the plan out by carrying it out on a copy of the shelves."""

    def __init__(self, situation: Situation):
        self.size = max(1, situation.table_size)
        self.goes_to = _goes_to(situation)
        self.left_out = situation.left_out
        self.order = {shelf: index for index, shelf in enumerate(situation.target)}
        self.rows = {shelf: list(row) for shelf, row in situation.rows.items()}
        for shelf in situation.target:
            self.rows.setdefault(shelf, [])
        self.width = situation.widths
        self.fill = {shelf: sum(self._width(a) for a in row) for shelf, row in self.rows.items()}
        target_fill = {shelf: sum(self._width(a) for a in row) for shelf, row in situation.target.items()}
        # A shelf counts as at least as wide as what stands on it now and what it will hold: a
        # width from the workbook is an estimate that comes out too narrow.
        self.room = {
            shelf: max(situation.room.get(shelf, 0.0), self.fill[shelf], target_fill.get(shelf, 0.0))
            for shelf in self.rows
        }
        self.table = list(situation.table)
        self.aside = list(situation.aside)
        self.settled = _staying(self.rows, situation.target, self.goes_to)
        on_shelves = {album for row in self.rows.values() for album in row}
        self.nowhere = sorted(set(self.goes_to) - on_shelves - set(self.table) - set(self.aside))
        self.rounds: list[list[Step]] = []
        self.steps: list[Step] = []
        self.taken = situation.taken

    def _width(self, album: int) -> float:
        return self.width.get(album, 0.0)

    def run(self) -> list[list[Step]]:
        taken = self.taken
        # Every album passes over the table a few times at most; this bounds a plan gone wrong.
        for _ in range(20 * (len(self._movers()) + len(self.table) + 10)):
            self._put_what_fits()
            if not self.table and self.steps and (taken >= self.size or not self._movers()):
                self.rounds.append(self.steps)
                self.steps, taken = [], 0
            if not self.table and not self._movers():
                break
            # A table full taken this round: only what empties the table is taken still.
            batch = self._choose(self.size - len(self.table), emptying=taken >= self.size)
            if batch:
                self._take(*batch)
                taken += len(batch[1])
            elif self.table:
                # Nothing fits anywhere and nothing frees room: the table is not enough.
                self._step(StepKind.SET_ASIDE, self.table, None)
                self.aside += self.table
                self.table = []
            else:
                break
        if self.steps:
            self.rounds.append(self.steps)
        return self.rounds

    def _movers(self) -> list[tuple[object, int]]:
        """Every album still to move, with where it is: a shelf, NOWHERE or ASIDE."""
        found: list[tuple[object, int]] = [(ASIDE, album) for album in self.aside]
        found += [(NOWHERE, album) for album in self.nowhere]
        for shelf, row in self.rows.items():
            found += [
                (shelf, album)
                for album in row
                if album not in self.settled and (album in self.goes_to or album in self.left_out)
            ]
        return found

    def _fits(self, album: int) -> bool:
        if album in self.left_out or album not in self.goes_to:
            return True
        shelf = self.goes_to[album][0]
        return self.fill[shelf] + self._width(album) <= self.room[shelf] + TOLERANCE_CM

    def _choose(self, space: int, emptying: bool = False) -> tuple[object, list[int]] | None:
        """Where to take from next, and which albums.

        Those that can go somewhere at once, else those making room on a shelf the table waits
        for. While emptying the table, only the latter, and only for what lies on the table.
        """
        if space <= 0:
            return None
        movers = self._movers()
        fitting = {} if emptying else self._fitting(movers, space)
        if fitting:
            source = max(fitting, key=lambda s: (len(fitting[s]), -self._source_rank(s)))
            return source, fitting[source]
        return self._making_room(movers, space, emptying)

    def _fitting(self, movers: list[tuple[object, int]], space: int) -> dict[object, list[int]]:
        """Per place to take from, the albums that can all go somewhere together.

        The room on each shelf is counted down as albums are taken for it.
        """
        sources: dict[object, list[int]] = {}
        for source, album in movers:
            sources.setdefault(source, []).append(album)
        fitting: dict[object, list[int]] = {}
        for source, albums in sources.items():
            left = {shelf: self.room[shelf] - self.fill[shelf] for shelf in self.room}
            chosen: list[int] = []
            for album in albums:
                shelf = None if album in self.left_out else self.goes_to.get(album, (None, 0))[0]
                if shelf is not None and self._width(album) > left[shelf] + TOLERANCE_CM:
                    continue
                if shelf is not None:
                    left[shelf] -= self._width(album)
                chosen.append(album)
                if len(chosen) == space:
                    break
            if chosen:
                fitting[source] = chosen
        return fitting

    def _making_room(
        self, movers: list[tuple[object, int]], space: int, emptying: bool
    ) -> tuple[object, list[int]] | None:
        """The albums to take out of a shelf the table, or another album, waits for."""
        waiting = [self.goes_to[a][0] for a in self.table if a in self.goes_to]
        if not emptying:
            waiting += [self.goes_to[a][0] for _, a in movers if a in self.goes_to]
        leavers: dict[object, list[int]] = {}
        for source, album in movers:
            if source in waiting:
                leavers.setdefault(source, []).append(album)
        if not leavers:
            return None
        first = waiting[0]
        source = max(leavers, key=lambda s: (s == first, len(leavers[s]), -self._source_rank(s)))
        return source, leavers[source][:space]

    def _source_rank(self, source: object) -> int:
        return {ASIDE: -2, NOWHERE: -1}.get(source, self.order.get(source, len(self.order)))  # type: ignore[arg-type]

    def _take(self, source: object, albums: list[int]) -> None:
        if source == ASIDE:
            self.aside = [a for a in self.aside if a not in albums]
            self._step(StepKind.TAKE_BACK, albums, None)
        elif source == NOWHERE:
            self.nowhere = [a for a in self.nowhere if a not in albums]
            self._step(StepKind.TAKE, albums, None)
        else:
            row = self.rows[source]
            albums = [a for a in row if a in set(albums)]
            self.rows[source] = [a for a in row if a not in set(albums)]
            self.fill[source] -= sum(self._width(a) for a in albums)
            self._step(StepKind.TAKE, albums, source)
        self.table += albums

    def _put_what_fits(self) -> None:
        def key(album: int) -> tuple:
            shelf, index = self.goes_to.get(album, (None, 0))
            return (shelf is not None, self.order.get(shelf, 0), index)

        for album in sorted(self.table, key=key):
            if album in self.left_out or album not in self.goes_to:
                self.table.remove(album)
                self._step(StepKind.LEAVE_OUT, [album], None)
            elif self._fits(album):
                self.table.remove(album)
                self._put(album)

    def _put(self, album: int) -> None:
        shelf, index = self.goes_to[album]
        row = self.rows[shelf]
        before = [a for a in row if a in self.settled and self.goes_to[a][1] < index]
        after = max(before, key=lambda a: self.goes_to[a][1]) if before else None
        row.insert(row.index(after) + 1 if after is not None else 0, album)
        self.fill[shelf] += self._width(album)
        self.settled.add(album)
        self._step(StepKind.PUT, [album], shelf, after)

    def _step(self, kind: StepKind, albums: Iterable[int], shelf: int | None, after: int | None = None) -> None:
        """Add a step, or add to the last one when it is the same thing at the same place."""
        albums = tuple(albums)
        last = self.steps[-1] if self.steps else None
        if last is not None and last.kind == kind and last.shelf_id == shelf:
            follows = kind != StepKind.PUT or after == last.album_ids[-1]
            if follows:
                self.steps[-1] = Step(kind, last.album_ids + albums, shelf, last.after_album_id)
                return
        self.steps.append(Step(kind, albums, shelf, after))



def carry_out(rows: dict[int, list[int]], table: list[int], aside: list[int], step: Step) -> None:
    """Do a step on the shelves, the table and what is set aside, in place.

    Args:
        rows: The albums on each shelf, in the order they stand.
        table: The albums on the table.
        aside: The albums set aside.
        step: The step.

    Raises:
        ValueError: The step does not fit the shelves as they stand: an album is not where the
            step takes it from, or the album to put after is not on the shelf.
    """
    albums = list(step.album_ids)
    if step.kind == StepKind.TAKE and step.shelf_id is not None:
        row = rows.get(step.shelf_id, [])
        if any(album not in row for album in albums):
            raise ValueError("not on that shelf")
        rows[step.shelf_id] = [album for album in row if album not in set(albums)]
        table += albums
    elif step.kind == StepKind.TAKE:
        table += albums
    elif step.kind == StepKind.TAKE_BACK:
        if any(album not in aside for album in albums):
            raise ValueError("not set aside")
        aside[:] = [album for album in aside if album not in set(albums)]
        table += albums
    else:
        if any(album not in table for album in albums):
            raise ValueError("not on the table")
        table[:] = [album for album in table if album not in set(albums)]
        if step.kind == StepKind.SET_ASIDE:
            aside += albums
        elif step.kind == StepKind.PUT:
            row = rows.setdefault(step.shelf_id, [])
            if step.after_album_id is not None and step.after_album_id not in row:
                raise ValueError("the album to put after is not on the shelf")
            start = row.index(step.after_album_id) + 1 if step.after_album_id is not None else 0
            row[start:start] = albums
