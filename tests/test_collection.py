"""Tests for the services that link, enrich and size the stored collection."""

from datetime import datetime

from sleeve_shelf.collection import (
    apply_enrichment,
    enrich_collection,
    import_discogs_collection,
)
from sleeve_shelf.config import Settings, load_settings, save_settings
from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    Cluster,
    MasterEnrichment,
    MatchProposal,
    ReleaseEnrichment,
    Style,
)
from sleeve_shelf.ingestion.discogs_csv import CollectionItem
from sleeve_shelf.ingestion.formats import parse_format
from sleeve_shelf.persistence import JsonStore

CONSTANTS = Settings().width_constants
NOW = datetime(2026, 10, 8, 12, 0, 0)


def _item(release_id, artist, title, format_text="LP, Album"):
    parsed = parse_format(format_text)
    return CollectionItem(release_id, artist, title, parsed.is_vinyl, parsed.tokens)


def test_import_links_loaded_albums_and_adds_the_rest(tmp_path):
    store = JsonStore(tmp_path)
    store.save(Artist, [Artist(1, "Tom Waits"), Artist(2, "Woody Herman And His Orchestra")])
    store.save(
        Album,
        [
            Album(1, 1, "Closing Time", format_tokens=parse_format("LP, Album, PR").tokens),
            Album(2, 1, "Closing Time", format_tokens=parse_format("2xLP, Album, RE").tokens),
            Album(3, 2, "The First Herd At Carnegie Hall"),
            Album(4, 1, "A Title Discogs Does Not Have"),
        ],
    )
    items = [
        _item(27265158, "Tom Waits", "Closing Time", "2xLP, Album, RE"),
        _item(1874289, "Tom Waits", "closing  time", "LP, Album, PR"),
        _item(1126311, "Woody Herman", "The First Herd At Carnegie Hall"),
        _item(1965832, "The Birthday Party", "The Bad Seed", '12", EP'),
        _item(395825, "The Birthday Party", "Junkyard", "CD, Album"),
    ]

    result = import_discogs_collection(store, items, CONSTANTS)

    albums = {album.id: album for album in store.load(Album)}
    # Two pressings of one title end up on the release with their own format.
    assert (albums[1].release_id, albums[2].release_id) == (1874289, 27265158)
    # A near match is proposed, not applied.
    assert albums[3].release_id is None
    assert store.load(MatchProposal) == [
        MatchProposal(
            3, 1126311, "Woody Herman", "The First Herd At Carnegie Hall", 0.83,
            parse_format("LP, Album").tokens,
        )
    ]
    assert albums[4].release_id is None
    # New vinyl becomes an album under a new artist; the CD is left out.
    assert (albums[5].title, albums[5].release_id) == ("The Bad Seed", 1965832)
    assert store.load(Artist)[-1] == Artist(3, "The Birthday Party")
    assert albums[2].computed_width_cm == 1.0
    assert (result.matched, result.proposed, result.added, result.unmatched_albums) == (2, 1, 1, 1)
    assert (result.vinyl_count, result.skipped_non_vinyl) == (4, 1)

    again = import_discogs_collection(store, items, CONSTANTS)
    assert (again.matched, again.added) == (0, 0)
    assert len(store.load(Album)) == 5

    # A release that left the Discogs collection is reported; its album stays.
    sold = import_discogs_collection(store, items[1:], CONSTANTS)
    assert sold.gone == (("Tom Waits", "Closing Time"),)
    assert len(store.load(Album)) == 5


class _Client:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def release(self, release_id):
        self.calls.append(("release", release_id))
        if release_id == self.fail_on:
            raise ConnectionError("network down")
        master_id = {10: 100, 11: 100}.get(release_id)
        return ReleaseEnrichment(release_id, ("Cool Jazz",), master_id, NOW, 2018)

    def master(self, master_id):
        self.calls.append(("master", master_id))
        return MasterEnrichment(master_id, 1959, NOW)


def test_enrichment_fetches_once_and_fills_the_albums(tmp_path):
    store = JsonStore(tmp_path)
    store.save(Cluster, [Cluster(1, "Jazz: Cool / West Coast")])
    store.save(Artist, [Artist(1, "Chet Baker"), Artist(2, "Someone New")])
    store.save(ArtistClusterAssignment, [ArtistClusterAssignment(1, 1, confirmed=True)])
    store.save(
        Album,
        [
            Album(1, 1, "Chet", release_id=10, original_release_year=2018),
            Album(
                2, 1, "Chet Again", release_id=11, original_release_year=1961,
                original_year_confirmed=True,
            ),
            Album(3, 2, "Private Press", release_id=12),
            Album(4, 2, "Not On Discogs"),
        ],
    )
    client = _Client()
    seen = []

    lookups = enrich_collection(store, client, lambda done, total: seen.append((done, total)))

    assert client.calls == [("release", 10), ("master", 100), ("release", 11), ("release", 12)]
    assert lookups == 4 and seen[-1] == (4, 4)
    first, second, third, fourth = store.load(Album)
    # The pressing year gives way to the master's; a confirmed year is left alone.
    assert (first.master_id, first.original_release_year) == (100, 1959)
    assert second.original_release_year == 1961
    # Without a master the release's own year is the original.
    assert (third.master_id, third.original_release_year) == (None, 2018)
    assert fourth.style_ids == []
    # The style joins the cluster its albums' artists were already curated into.
    assert store.load(Style) == [Style(1, "Cool Jazz", 1)]
    assert first.style_ids == [1]

    enrich_collection(store, client)
    assert len(client.calls) == 4


def test_interrupted_enrichment_keeps_what_was_fetched(tmp_path):
    store = JsonStore(tmp_path)
    store.save(Artist, [Artist(1, "Chet Baker")])
    store.save(Album, [Album(1, 1, "Chet", release_id=10), Album(2, 1, "More", release_id=12)])

    try:
        enrich_collection(store, _Client(fail_on=12))
    except ConnectionError:
        pass

    assert [release.release_id for release in store.load(ReleaseEnrichment)] == [10]
    resumed = _Client()
    enrich_collection(store, resumed)
    assert resumed.calls == [("release", 12)]


def test_style_without_a_curated_cluster_gets_its_own(tmp_path):
    store = JsonStore(tmp_path)
    store.save(Artist, [Artist(1, "Someone New")])
    store.save(Album, [Album(1, 1, "Debut", release_id=12)])
    store.save(ReleaseEnrichment, [ReleaseEnrichment(12, ("Dub",), None, NOW, 1979)])

    apply_enrichment(store)

    assert store.load(Cluster) == [Cluster(1, "Dub", position=0)]
    assert store.load(Style) == [Style(1, "Dub", 1)]


def test_settings_round_trip_and_default(tmp_path):
    assert load_settings(tmp_path) == Settings()

    save_settings(tmp_path, Settings(discogs_token="secret", base_width_cm=0.45))

    assert load_settings(tmp_path) == Settings(discogs_token="secret", base_width_cm=0.45)
