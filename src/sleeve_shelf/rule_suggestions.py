"""Application service for location-rule suggestions, read off the layout as it stands."""

from collections import Counter, defaultdict
from dataclasses import dataclass

from flask_babel import gettext as _

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
from sleeve_shelf.proposal import mandatory_cabinets, sort_collection, kept_shelf_ids, takes_part, usable_shelves
from sleeve_shelf.sorting.placement import place

# A cluster or artist is only read as "kept apart" from this many albums on.
MIN_ALBUMS = 2
# An album stands apart from its artist when at least this share of the artist's albums
# stands in one other cabinet, and the artist has at least this many albums.
ALBUM_MAJORITY = 0.75
ALBUM_MIN_ARTIST = 4


@dataclass(frozen=True, slots=True)
class RuleSuggestion:
    """A location rule the layout hints at: something standing where a proposal would not put it."""

    target_type: LocationRuleTarget
    target_id: int
    cabinet_id: int
    # The albums the suggestion is read from, and the cabinet a proposal would give them.
    album_count: int
    proposed_cabinet_id: int | None


def rule_suggestions(store: JsonStore) -> list[RuleSuggestion]:
    """The rules the current layout hints at; none is ever made without the user accepting it.

    The layout is compared with the proposal generated without any rule. A
    cluster, family or artist whose albums all stand in one cabinet, while that
    proposal would put most of them in a cabinet more than one step away in
    walking order, is kept there on purpose — so is an album standing apart
    from the rest of its artist. The most general explanation is suggested: a
    target covered by a suggestion or an existing rule on something that
    contains it is skipped, and so is a suggestion the user turned down.
    """
    albums = store.load(Album)
    placed = {p.album_id: p for p in store.load(Placement)}
    if not albums or not placed:
        return []
    shelves = {shelf.id: shelf for shelf in store.load(Shelf)}
    cabinets = in_order(store.load(Cabinet))
    walk = {cabinet.id: index for index, cabinet in enumerate(cabinets)}
    placed_ids = set(placed)
    current = {
        album.id: shelves[placed[album.id].shelf_id].cabinet_id
        for album in albums
        if album.id in placed and takes_part(album, placed_ids)
    }

    proposed = _proposed_cabinets(store)
    if proposed is None:
        return []

    def far(a: int | None, b: int | None) -> bool:
        return a is not None and b is not None and a != b and abs(walk[a] - walk[b]) > 1

    def all_in(ids: list[int]) -> int | None:
        cabinet, count = Counter(current[i] for i in ids).most_common(1)[0]
        return cabinet if count == len(ids) else None

    def proposal_for(ids: list[int]) -> int | None:
        return Counter(proposed.get(i) for i in ids).most_common(1)[0][0]

    assignments = {a.artist_id: a.cluster_id for a in store.load(ArtistClusterAssignment)}
    family_of = {artist.id: artist.alias_group_id for artist in store.load(Artist)}
    existing = {
        (rule.target_type, rule.target_id): rule.cabinet_id for rule in store.load(LocationRule)
    }
    dismissed = {
        (d.target_type, d.target_id, d.cabinet_id) for d in store.load(RuleSuggestionDismissal)
    }

    by_artist: dict[int, list[int]] = defaultdict(list)
    for album_id in current:
        by_artist[next(a.artist_id for a in albums if a.id == album_id)].append(album_id)
    artist_of = {album.id: album.artist_id for album in albums}
    by_cluster: dict[int, list[int]] = defaultdict(list)
    by_family: dict[int, list[int]] = defaultdict(list)
    for album_id in current:
        artist_id = artist_of[album_id]
        if artist_id in assignments and assignments[artist_id] is not None:
            by_cluster[assignments[artist_id]].append(album_id)
        if family_of.get(artist_id) is not None:
            by_family[family_of[artist_id]].append(album_id)

    suggestions: list[RuleSuggestion] = []
    # album id -> the cabinet a rule, or a more general suggestion or dismissal, already
    # accounts for; an album standing there needs nothing more specific.
    covered: dict[int, int] = {}
    groups_by_kind = (
        (LocationRuleTarget.CLUSTER, by_cluster),
        (LocationRuleTarget.ALIAS_GROUP, by_family),
        (LocationRuleTarget.ARTIST, by_artist),
    )
    for kind, groups in groups_by_kind:
        for target_id, ids in groups.items():
            if (kind, target_id) in existing:
                for album_id in ids:
                    covered[album_id] = existing[(kind, target_id)]
    album_rules = {
        target_id: cabinet_id
        for (kind, target_id), cabinet_id in existing.items()
        if kind is LocationRuleTarget.ALBUM
    }

    def consider(kind: LocationRuleTarget, target_id: int, ids: list[int]) -> None:
        if len(ids) < MIN_ALBUMS or (kind, target_id) in existing:
            return
        cabinet = all_in(ids)
        if cabinet is None or all(covered.get(i) == cabinet for i in ids):
            return
        # Where the albums would go as things stand: the cabinet a rule or a more general
        # choice gives them, else where the proposal puts them.
        expected = Counter(covered.get(i, proposed.get(i)) for i in ids).most_common(1)[0][0]
        if not far(cabinet, expected):
            return
        if (kind, target_id, cabinet) in dismissed:
            # Turned down: what it contains is not suggested one level lower either.
            for album_id in ids:
                covered[album_id] = cabinet
            return
        suggestions.append(RuleSuggestion(kind, target_id, cabinet, len(ids), expected))
        for album_id in ids:
            covered[album_id] = cabinet

    for kind, groups in groups_by_kind:
        for target_id, ids in groups.items():
            consider(kind, target_id, ids)

    # One album kept apart from the rest of its artist: a box set in external storage.
    for artist_id, ids in by_artist.items():
        if len(ids) < ALBUM_MIN_ARTIST:
            continue
        majority, count = Counter(current[i] for i in ids).most_common(1)[0]
        if count / len(ids) < ALBUM_MAJORITY:
            continue
        for album_id in ids:
            cabinet = current[album_id]
            if cabinet == majority or (LocationRuleTarget.ALBUM, album_id) in existing:
                continue
            if covered.get(album_id) == cabinet:
                continue
            if album_id in album_rules:
                continue
            expected = covered.get(album_id, proposed.get(album_id))
            if far(cabinet, expected) and far(cabinet, majority):
                if (LocationRuleTarget.ALBUM, album_id, cabinet) not in dismissed:
                    suggestions.append(
                        RuleSuggestion(
                            LocationRuleTarget.ALBUM, album_id, cabinet, 1, proposed.get(album_id)
                        )
                    )
    return suggestions


def accept_suggestions(store: JsonStore, cabinet_id: int) -> int:
    """Turn every suggestion for a cabinet into a rule; returns how many rules were made."""
    chosen = [s for s in rule_suggestions(store) if s.cabinet_id == cabinet_id]
    if not chosen:
        return 0
    rules = store.load(LocationRule)
    for suggestion in chosen:
        rules.append(
            LocationRule(
                store.next_id(LocationRule, rules),
                suggestion.target_type,
                suggestion.target_id,
                cabinet_id,
                _("Suggested from the layout"),
            )
        )
    store.save(LocationRule, rules)
    return len(chosen)


def dismiss_suggestions(store: JsonStore, cabinet_id: int) -> int:
    """Turn the suggestions for a cabinet down for good; returns how many."""
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
