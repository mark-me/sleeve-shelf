"""Application services for artist families (alias groups)."""

from sleeve_shelf.domain import AliasGroup, Artist, FamilyDismissal
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.sorting.families import FamilySuggestion, suggest_families


def family_suggestions(store: JsonStore) -> list[FamilySuggestion]:
    """Families suggested from the artist names, minus the ones turned down."""
    dismissed = {dismissal.anchor_artist_id for dismissal in store.load(FamilyDismissal)}
    return suggest_families(store.load(Artist), dismissed)


def create_family(store: JsonStore, label: str, artist_ids: list[int] | None = None) -> AliasGroup:
    """Add a family, optionally with its first members."""
    groups = store.load(AliasGroup)
    group = AliasGroup(max((g.id for g in groups), default=0) + 1, label)
    groups.append(group)
    store.save(AliasGroup, groups)
    if artist_ids:
        artists = store.load(Artist)
        for artist in artists:
            if artist.id in artist_ids:
                artist.alias_group_id = group.id
        store.save(Artist, artists)
    return group


def accept_suggestion(store: JsonStore, anchor_id: int, member_ids: list[int]) -> None:
    """Turn a suggestion into a family, named after its anchor, with the chosen members."""
    suggestion = next((s for s in family_suggestions(store) if s.anchor_id == anchor_id), None)
    if suggestion is None:
        return
    chosen = [member_id for member_id in suggestion.member_ids if member_id in member_ids]
    if not chosen:
        return
    anchor = next(artist for artist in store.load(Artist) if artist.id == anchor_id)
    create_family(store, anchor.name, [anchor_id, *chosen])


def dismiss_suggestion(store: JsonStore, anchor_id: int) -> None:
    dismissals = store.load(FamilyDismissal)
    if all(dismissal.anchor_artist_id != anchor_id for dismissal in dismissals):
        store.save(FamilyDismissal, [*dismissals, FamilyDismissal(anchor_id)])


def rename_family(store: JsonStore, group_id: int, label: str) -> None:
    groups = store.load(AliasGroup)
    for group in groups:
        if group.id == group_id:
            group.label = label
    store.save(AliasGroup, groups)


def delete_family(store: JsonStore, group_id: int) -> None:
    """Remove a family; its artists stand on their own again."""
    artists = store.load(Artist)
    for artist in artists:
        if artist.alias_group_id == group_id:
            artist.alias_group_id = None
    store.save(Artist, artists)
    store.save(AliasGroup, [group for group in store.load(AliasGroup) if group.id != group_id])


def set_family(store: JsonStore, artist_id: int, group_id: int | None) -> None:
    """Put an artist in a family, or take it out with group_id None."""
    artists = store.load(Artist)
    for artist in artists:
        if artist.id == artist_id:
            artist.alias_group_id = group_id
    store.save(Artist, artists)
