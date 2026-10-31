"""Application service for location-rule suggestions, read off the layout as it stands."""

from collections import Counter, defaultdict
from dataclasses import dataclass

from sleeve_shelf.config import load_settings
from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    Cabinet,
    LocationRule,
    LocationRuleTarget,
    Placement,
    RuleSuggestionDismissal,
    Shelf,
    in_order,
)
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.shelving.placing import set_rule
from sleeve_shelf.shelving.proposal import sort_collection
from sleeve_shelf.sorting.placement import place
from sleeve_shelf.library.taking_part import kept_shelf_ids, takes_part, usable_shelves

# A cluster or artist is only read as "kept apart" from this many albums on.
MIN_ALBUMS = 2
# An album stands apart from its artist when at least this share of the artist's albums
# stands in one other cabinet, and the artist has at least this many albums.
ALBUM_MAJORITY = 0.75
ALBUM_MIN_ARTIST = 4


@dataclass(frozen=True, slots=True)
class RuleSuggestion:
    """A location rule the layout hints at: something standing where a proposal would not put it.

    Attributes:
        target_type: What the rule would bind.
        target_id: The id of that.
        cabinet_id: The cabinet it stands in.
        album_count: The albums the suggestion is read from.
        proposed_cabinet_id: The cabinet a proposal would give them.
    """

    target_type: LocationRuleTarget
    target_id: int
    cabinet_id: int
    album_count: int
    proposed_cabinet_id: int | None


def _groups(store: JsonStore, albums: list[Album], current: dict[int, int]) -> tuple[dict[int, list[int]], tuple]:
    """The albums standing on a shelf per artist, and per kind of target the albums of each."""
    assignments = {a.artist_id: a.cluster_id for a in store.load(ArtistClusterAssignment)}
    family_of = {artist.id: artist.alias_group_id for artist in store.load(Artist)}
    artist_of = {album.id: album.artist_id for album in albums}
    by_artist: dict[int, list[int]] = defaultdict(list)
    by_cluster: dict[int, list[int]] = defaultdict(list)
    by_family: dict[int, list[int]] = defaultdict(list)
    for album_id in current:
        artist_id = artist_of[album_id]
        by_artist[artist_id].append(album_id)
        if artist_id in assignments and assignments[artist_id] is not None:
            by_cluster[assignments[artist_id]].append(album_id)
        if family_of.get(artist_id) is not None:
            by_family[family_of[artist_id]].append(album_id)
    return by_artist, (
        (LocationRuleTarget.CLUSTER, by_cluster),
        (LocationRuleTarget.ALIAS_GROUP, by_family),
        (LocationRuleTarget.ARTIST, by_artist),
    )


class _Reading:
    """Reading the layout against the proposal, the most general targets first."""

    def __init__(self, store: JsonStore, current: dict[int, int], proposed: dict[int, int | None]) -> None:
        self.current = current
        self.proposed = proposed
        self.walk = {cabinet.id: index for index, cabinet in enumerate(in_order(store.load(Cabinet)))}
        self.existing = {
            (rule.target_type, rule.target_id): rule.cabinet_id for rule in store.load(LocationRule)
        }
        self.dismissed = {
            (d.target_type, d.target_id, d.cabinet_id) for d in store.load(RuleSuggestionDismissal)
        }
        self.album_rules = {
            target_id: cabinet_id
            for (kind, target_id), cabinet_id in self.existing.items()
            if kind is LocationRuleTarget.ALBUM
        }
        self.suggestions: list[RuleSuggestion] = []
        # album id -> the cabinet a rule, or a more general suggestion or dismissal, already
        # accounts for; an album standing there needs nothing more specific.
        self.covered: dict[int, int] = {}

    def _far(self, a: int | None, b: int | None) -> bool:
        return a is not None and b is not None and a != b and abs(self.walk[a] - self.walk[b]) > 1

    def _all_in(self, ids: list[int]) -> int | None:
        cabinet, count = Counter(self.current[i] for i in ids).most_common(1)[0]
        return cabinet if count == len(ids) else None

    def cover_by_rules(self, groups_by_kind: tuple) -> None:
        for kind, groups in groups_by_kind:
            for target_id, ids in groups.items():
                if (kind, target_id) in self.existing:
                    for album_id in ids:
                        self.covered[album_id] = self.existing[(kind, target_id)]

    def consider(self, kind: LocationRuleTarget, target_id: int, ids: list[int]) -> None:
        if len(ids) < MIN_ALBUMS or (kind, target_id) in self.existing:
            return
        cabinet = self._all_in(ids)
        if cabinet is None or all(self.covered.get(i) == cabinet for i in ids):
            return
        # Where the albums would go as things stand: the cabinet a rule or a more general
        # choice gives them, else where the proposal puts them.
        expected = Counter(self.covered.get(i, self.proposed.get(i)) for i in ids).most_common(1)[0][0]
        if not self._far(cabinet, expected):
            return
        # Turned down: what it contains is not suggested one level lower either.
        if (kind, target_id, cabinet) not in self.dismissed:
            self.suggestions.append(RuleSuggestion(kind, target_id, cabinet, len(ids), expected))
        for album_id in ids:
            self.covered[album_id] = cabinet

    def consider_albums_apart(self, ids: list[int]) -> None:
        if len(ids) < ALBUM_MIN_ARTIST:
            return
        majority, count = Counter(self.current[i] for i in ids).most_common(1)[0]
        if count / len(ids) < ALBUM_MAJORITY:
            return
        for album_id in ids:
            cabinet = self.current[album_id]
            if cabinet == majority or self.covered.get(album_id) == cabinet or album_id in self.album_rules:
                continue
            expected = self.covered.get(album_id, self.proposed.get(album_id))
            if (
                self._far(cabinet, expected)
                and self._far(cabinet, majority)
                and (LocationRuleTarget.ALBUM, album_id, cabinet) not in self.dismissed
            ):
                self.suggestions.append(
                    RuleSuggestion(LocationRuleTarget.ALBUM, album_id, cabinet, 1, self.proposed.get(album_id))
                )


def rule_suggestions(store: JsonStore) -> list[RuleSuggestion]:
    """The rules the current layout hints at; none is ever made without the user accepting it.

    The layout is compared with the proposal generated without any rule. A cluster, family or artist
    whose albums all stand in one cabinet, while that proposal would put most of them in a cabinet
    more than one step away in walking order, is kept there on purpose — so is an album standing
    apart from the rest of its artist. The most general explanation is suggested: a target covered
    by a suggestion or an existing rule on something that contains it is skipped, and so is a
    suggestion the user turned down.

    Args:
        store: The store of the collection.

    Returns:
        The suggestions.
    """
    albums = store.load(Album)
    placed = {p.album_id: p for p in store.load(Placement)}
    if not albums or not placed:
        return []
    shelves = {shelf.id: shelf for shelf in store.load(Shelf)}
    placed_ids = set(placed)
    current = {
        album.id: shelves[placed[album.id].shelf_id].cabinet_id
        for album in albums
        if album.id in placed and takes_part(album, placed_ids)
    }
    proposed = _proposed_cabinets(store)
    if proposed is None:
        return []

    reading = _Reading(store, current, proposed)
    by_artist, groups_by_kind = _groups(store, albums, current)
    reading.cover_by_rules(groups_by_kind)
    for kind, groups in groups_by_kind:
        for target_id, ids in groups.items():
            reading.consider(kind, target_id, ids)
    # One album kept apart from the rest of its artist: a box set in external storage.
    for ids in by_artist.values():
        reading.consider_albums_apart(ids)
    return reading.suggestions


def accept_suggestions(store: JsonStore, cabinet_id: int, note: str) -> int:
    """Turn every suggestion for a cabinet into a rule.

    Args:
        store: The store of the collection.
        cabinet_id: The cabinet.
        note: The note each rule gets.

    Returns:
        How many rules were made.
    """
    chosen = [s for s in rule_suggestions(store) if s.cabinet_id == cabinet_id]
    if not chosen:
        return 0
    for suggestion in chosen:
        set_rule(store, suggestion.target_type, suggestion.target_id, cabinet_id, note)
    return len(chosen)


def dismiss_suggestions(store: JsonStore, cabinet_id: int) -> int:
    """Turn the suggestions for a cabinet down for good.

    Args:
        store: The store of the collection.
        cabinet_id: The cabinet.

    Returns:
        How many were turned down.
    """
    chosen = [s for s in rule_suggestions(store) if s.cabinet_id == cabinet_id]
    if not chosen:
        return 0
    dismissals = store.load(RuleSuggestionDismissal)
    dismissals += [
        RuleSuggestionDismissal(s.target_type, s.target_id, s.cabinet_id) for s in chosen
    ]
    store.save(RuleSuggestionDismissal, dismissals)
    return len(chosen)


def _proposed_cabinets(store: JsonStore) -> dict[int, int | None] | None:
    """Where a proposal without any location rule would stand each album; None if it cannot run."""
    constants = load_settings(store.data_dir).width_constants
    result = sort_collection(store)
    kept = kept_shelf_ids(store)
    shown = {p.album_id for p in store.load(Placement) if p.shelf_id in kept}
    albums = [
        (o.album_id, result.albums[o.album_id].width_cm or constants.base_per_disc, None)
        for o in result.ordered
        if o.album_id not in shown
    ]
    usable, _skipped = usable_shelves(store)
    if not usable:
        return None
    spots, _left = place(albums, [(x.id, x.cabinet_id, x.width_cm) for x in usable])
    shelves = {shelf.id: shelf for shelf in store.load(Shelf)}
    return {spot.album_id: shelves[spot.shelf_id].cabinet_id for spot in spots}
