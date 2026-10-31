"""The network as the Connections screen and an album's page need it, from the collection as
it stands; and the pairs of names the owner said are not related."""

from sleeve_shelf.config import load_settings
from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    ArtistEnrichment,
    Cluster,
    ReleaseEnrichment,
    UnrelatedArtists,
)
from sleeve_shelf.insights.network import Network, Tied, build, songs_elsewhere, tied_albums
from sleeve_shelf.insights.ties import Tie
from sleeve_shelf.persistence import JsonStore


def ties_of(store: JsonStore, shown: Network, artist_id: int, leave_out: frozenset[Tie] = frozenset()) -> list[Tied]:
    """The ties of one artist in the network, with the albums that show them; artists tied only
    by the kinds left out are not among them."""
    releases = store.load(ReleaseEnrichment)
    albums = store.load(Album)
    around = [pair for pair in shown.around(artist_id) if set(pair[1].ties) - leave_out]
    left_out = load_settings(store.data_dir).labels_left_out
    return tied_albums(around, artist_id, store.load(Artist), albums, releases, left_out)


def album_songs_elsewhere(store: JsonStore, album_id: int) -> list[tuple[str, tuple[int, ...]]]:
    """The songs of an album that other albums of the collection have too (see songs_elsewhere)."""
    if not store.exists(ReleaseEnrichment):
        return []
    return songs_elsewhere(album_id, store.load(Artist), store.load(Album), store.load(ReleaseEnrichment))


def network(store: JsonStore) -> Network:
    """The network of the collection as it stands."""
    if not store.exists(Artist):
        return Network((), (), ())

    return build(
        store.load(Artist),
        store.load(Album),
        store.load(ArtistEnrichment),
        store.load(ReleaseEnrichment),
        store.load(ArtistClusterAssignment),
        store.load(Cluster),
        load_settings(store.data_dir).labels_left_out,
        unrelated_pairs(store),
    )


def unrelated_pairs(store: JsonStore) -> set[tuple[int, int]]:
    """The artists the user says are not related, each pair with the lower id first."""
    return {(pair.one, pair.other) for pair in store.load(UnrelatedArtists)}


def set_unrelated(store: JsonStore, one: int, other: int, unrelated: bool) -> None:
    """Say that a name inside another does not make two artists related, or take that back."""
    pair = UnrelatedArtists(min(one, other), max(one, other))
    pairs = [existing for existing in store.load(UnrelatedArtists) if existing != pair]
    store.save(UnrelatedArtists, [*pairs, pair] if unrelated else pairs)
