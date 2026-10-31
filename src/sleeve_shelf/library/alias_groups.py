"""Application services for artist families (alias groups)."""

from sleeve_shelf.library.artists import albums_per_artist
from sleeve_shelf.config import load_settings
from sleeve_shelf.domain import (
    AliasGroup,
    Artist,
    ArtistClusterAssignment,
    ArtistEnrichment,
    FamilyDismissal,
    UnrelatedArtists,
)
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.sorting.connections import ClusterHint, clusters_by_connection
from sleeve_shelf.sorting.families import FamilySuggestion, suggest_families


def family_suggestions(store: JsonStore) -> list[FamilySuggestion]:
    """Families suggested from the artist names and from Discogs, minus the ones turned down."""
    dismissed = {dismissal.anchor_artist_id for dismissal in store.load(FamilyDismissal)}
    album_counts = albums_per_artist(store)
    return suggest_families(
        store.load(Artist),
        dismissed,
        store.load(ArtistEnrichment),
        album_counts,
        load_settings(store.data_dir).sideman_bands,
        {(pair.one, pair.other) for pair in store.load(UnrelatedArtists)},
    )


def cluster_hints(store: JsonStore) -> dict[int, ClusterHint]:
    """Per artist without a confirmed cluster: the cluster of whom Discogs connects it to.

    Also for an artist a family is suggested for: the cluster is proposed whether or not
    the family is accepted.
    """
    album_counts = albums_per_artist(store)
    return clusters_by_connection(
        store.load(Artist),
        store.load(ArtistClusterAssignment),
        store.load(ArtistEnrichment),
        album_counts,
        load_settings(store.data_dir).sideman_bands,
    )


def create_family(store: JsonStore, label: str, artist_ids: list[int] | None = None) -> AliasGroup:
    """Add a family, optionally with its first members."""
    groups = store.load(AliasGroup)
    group = AliasGroup(store.next_id(AliasGroup, groups), label)
    groups.append(group)
    store.save(AliasGroup, groups)
    if artist_ids:
        artists = store.load(Artist)
        for artist in artists:
            if artist.id in artist_ids:
                artist.alias_group_id = group.id
        store.save(Artist, artists)
    return group


def _suggestion(store: JsonStore, anchor_id: int, source: str | None) -> FamilySuggestion | None:
    """The suggestion with this anchor and, when given, from this source: from the names and
    from Discogs a family can be offered additions at once, under the same artist."""
    return next(
        (
            s
            for s in family_suggestions(store)
            if s.anchor_id == anchor_id and (source is None or s.source == source)
        ),
        None,
    )


def accept_suggestion(
    store: JsonStore, anchor_id: int, member_ids: list[int], source: str | None = None
) -> None:
    """Turn a suggestion into a family named after its anchor, or add to the family it names
    — which takes a member out of the family it was in, when it is suggested to move."""
    suggestion = _suggestion(store, anchor_id, source)
    if suggestion is None:
        return
    chosen = [member_id for member_id in suggestion.member_ids if member_id in member_ids]
    if not chosen:
        return
    if suggestion.group_id is not None:
        artists = store.load(Artist)
        for artist in artists:
            if artist.id in chosen:
                artist.alias_group_id = suggestion.group_id
        store.save(Artist, artists)
        return
    anchor = next(artist for artist in store.load(Artist) if artist.id == anchor_id)
    create_family(store, anchor.name, [anchor_id, *chosen])


def dismiss_suggestion(store: JsonStore, anchor_id: int, source: str | None = None) -> None:
    """Turn a suggestion down: a new family by its anchor, an addition by the artists to add."""
    suggestion = _suggestion(store, anchor_id, source)
    turned_down = [anchor_id]
    if suggestion is not None and suggestion.group_id is not None:
        turned_down = list(suggestion.member_ids)
    dismissals = store.load(FamilyDismissal)
    known = {dismissal.anchor_artist_id for dismissal in dismissals}
    new = [FamilyDismissal(artist_id) for artist_id in turned_down if artist_id not in known]
    if new:
        store.save(FamilyDismissal, [*dismissals, *new])


def join(store: JsonStore, artist_id: int, with_id: int) -> None:
    """Put an artist with another one, in that one's family — or a new family named after
    it when it has none: a joint billing put with another artist it names."""
    artists = store.load(Artist)
    artist = next((a for a in artists if a.id == artist_id), None)
    other = next((a for a in artists if a.id == with_id), None)
    if artist is None or other is None or artist_id == with_id:
        return
    if other.alias_group_id is None:
        create_family(store, other.name, [with_id, artist_id])
        return
    artist.alias_group_id = other.alias_group_id
    store.save(Artist, artists)


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
