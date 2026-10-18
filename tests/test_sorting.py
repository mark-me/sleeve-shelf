"""Tests for the sorting engine: era bands, families, units, and shelf order."""

from datetime import datetime

import pytest

from sleeve_shelf.domain import (
    Album,
    AliasGroup,
    Artist,
    ArtistClusterAssignment,
    ArtistEnrichment,
    Cluster,
    FormatTokens,
    Style,
)
from sleeve_shelf.sorting.connections import (
    ClusterHint,
    Connections,
    clusters_by_connection,
    connections_of,
)
from sleeve_shelf.sorting.eras import band_of
from sleeve_shelf.sorting.families import suggest_families
from sleeve_shelf.sorting.order import (
    OrderedAlbum,
    build_units,
    cluster_order_from_layout,
    order_albums,
    propose_cluster,
)
from sleeve_shelf.sorting.spots import SuggestedSpot, suggest_spots

NOW = datetime(2026, 10, 12)


@pytest.mark.parametrize(
    ("year", "band"),
    [(1949, "before 1960"), (1960, "1960s"), (1969, "1960s"), (1992, "1990s"),
     (2019, "2010s"), (2020, "2020s+"), (2031, "2020s+"), (None, "unknown"), (0, "unknown")],
)
def test_era_band_is_the_decade_of_the_start_year(year, band):
    assert band_of(year) == band


def _enrichment(artist_id, members=(), groups=(), aliases=()):
    return ArtistEnrichment(
        artist_id, None, None, NOW,
        member_ids=tuple(members), group_ids=tuple(groups), alias_ids=tuple(aliases),
    )


def test_families_are_suggested_from_discogs_membership_groups_and_aliases():
    artists = [
        Artist(1, "Nick Cave", discogs_artist_id=101),
        Artist(2, "Grinderman", discogs_artist_id=102),
        Artist(3, "The Birthday Party", discogs_artist_id=103),
        Artist(4, "Bonnie 'Prince' Billy", discogs_artist_id=104),
        Artist(5, "Palace Music", discogs_artist_id=105),
        Artist(6, "Session Player", discogs_artist_id=106),
        Artist(7, "Band One", discogs_artist_id=107),
        Artist(8, "Band Two", discogs_artist_id=108),
        Artist(9, "Band Three", discogs_artist_id=109),
        Artist(10, "Band Four", discogs_artist_id=110),
        Artist(11, "Paul Simon", discogs_artist_id=111),
        Artist(12, "Art Garfunkel", discogs_artist_id=112),
        Artist(13, "Simon & Garfunkel (2)", discogs_artist_id=113),
        Artist(14, "Not On Discogs"),
    ]
    enrichments = [
        # A person: Discogs lists the bands he is in, also ones outside the collection.
        _enrichment(101, groups=(102, 999)),
        _enrichment(102, members=(101, 998)),
        # A band can name a member whose own record does not name the band.
        _enrichment(103, members=(101,)),
        # Two names of one artist; the second has the most albums.
        _enrichment(104, aliases=(105,)),
        _enrichment(105, aliases=(104,)),
        # A sideman is in more bands of the collection than says anything.
        _enrichment(106, groups=(107, 108, 109, 110)),
        _enrichment(107, members=(106,)),
        # A band of two artists in the collection belongs to neither.
        _enrichment(113, members=(111, 112)),
        # A record from before membership was kept.
        ArtistEnrichment(108, None, None, NOW),
    ]

    suggestions = suggest_families(
        artists, enrichments=enrichments, album_counts={5: 3, 4: 1}, max_bands=3
    )

    assert [(s.anchor_id, s.member_ids, s.group_id, s.source) for s in suggestions] == [
        # The person anchors the family of his bands, which is named after him.
        (1, (2, 3), None, "discogs"),
        (5, (4,), None, "discogs"),
    ]
    # Turning down the artist a family would be named after settles it.
    assert suggest_families(artists, {1, 5}, enrichments, max_bands=3) == []
    # With room for four bands, the person in four is no sideman and gathers his bands.
    wider = suggest_families(artists, enrichments=enrichments, album_counts={5: 3, 4: 1})
    assert {s.anchor_id: set(s.member_ids) for s in wider}[6] == {7, 8, 9, 10}


def test_discogs_adds_to_an_existing_family_and_leaves_what_names_suggest():
    artists = [
        Artist(1, "Nick Cave", discogs_artist_id=101, alias_group_id=9),
        Artist(2, "Grinderman", discogs_artist_id=102, alias_group_id=9),
        Artist(3, "The Birthday Party", discogs_artist_id=103),
        Artist(4, "Nick Cave & Warren Ellis", discogs_artist_id=104, alias_group_id=9),
        Artist(5, "Jason Molina", discogs_artist_id=105),
        Artist(6, "Jason Molina Band", discogs_artist_id=106),
        Artist(7, "Songs: Ohia", discogs_artist_id=107, alias_group_id=3),
        Artist(8, "Magnolia Electric Co.", discogs_artist_id=108, alias_group_id=4),
        Artist(9, "Pyramid Electric", discogs_artist_id=109),
    ]
    enrichments = [
        _enrichment(101, groups=(102, 103)),
        # Names already suggest this pair: Discogs does not suggest it a second time.
        _enrichment(105, groups=(106,)),
        # Other names in two families of the user's own making: left alone.
        _enrichment(109, aliases=(107, 108)),
    ]

    suggestions = suggest_families(artists, enrichments=enrichments)

    assert [(s.anchor_id, s.member_ids, s.group_id, s.source) for s in suggestions] == [
        (5, (6,), None, "names"),
        # Offered to the family Nick Cave is in, shown by its artist with the lowest id.
        (1, (3,), 9, "discogs"),
    ]
    # Turning down the artist to add settles it.
    assert [s.source for s in suggest_families(artists, {3}, enrichments)] == ["names"]


def test_families_are_suggested_from_names():
    artists = [
        Artist(1, "Chet Baker"),
        Artist(2, "Chet Baker Quartet"),
        Artist(3, "Chet Baker & Crew"),
        Artist(4, "Duke Ellington"),
        Artist(5, "John Coltrane"),
        Artist(6, "Duke Ellington & John Coltrane"),
        Artist(7, "Miles Davis"),
        Artist(8, "The Miles Davis Quintet"),
        Artist(9, "The Miles Davis Quintet Together With Gil Evans"),
        Artist(10, "Melanie (2)"),
        Artist(11, "Melanie And Friends"),
        Artist(12, "Bakery"),
    ]

    suggestions = {s.anchor_id: s.member_ids for s in suggest_families(artists)}

    assert suggestions == {
        1: (3, 2),
        # Named first wins: the duet goes to Ellington, not Coltrane.
        4: (6,),
        7: (8, 9),
        10: (11,),
    }


def test_grouped_artists_and_dismissed_anchors_are_not_suggested():
    artists = [
        Artist(1, "Chet Baker"),
        Artist(2, "Chet Baker Quartet", alias_group_id=5),
        Artist(3, "Rex"),
        Artist(4, "T. Rex"),
    ]

    assert suggest_families(artists, {3}) == []


def test_cluster_is_proposed_from_styles_with_the_earliest_album_breaking_a_tie():
    styles = {1: Style(1, "Cool Jazz", 10), 2: Style(2, "Hard Bop", 20), 3: Style(3, "Bop", 20)}

    assert propose_cluster([Album(1, 1, "a", style_ids=[1, 2, 3])], styles) == 20
    tied = [
        Album(1, 1, "late", style_ids=[1], original_release_year=1970),
        Album(2, 1, "early", style_ids=[2], original_release_year=1958),
    ]
    assert propose_cluster(tied, styles) == 20
    assert propose_cluster([Album(1, 1, "no styles")], styles) is None


def test_albums_stand_by_cluster_band_unit_year_and_title():
    clusters = [Cluster(1, "Jazz", position=1), Cluster(2, "Rock", position=0)]
    artists = [
        Artist(1, "Chet Baker", start_year=1949, alias_group_id=1),
        Artist(2, "Chet Baker Quartet", alias_group_id=1),
        Artist(3, "Art Pepper", start_year=1951),
        Artist(4, "Zoot Sims", start_year=1944),
        Artist(5, "The Stooges", start_year=1967),
        Artist(6, "New Band"),
    ]
    albums = [
        Album(1, 1, "Chet", original_release_year=1959),
        Album(2, 2, "Quartet", original_release_year=1955),
        Album(3, 1, "Undated"),
        Album(4, 3, "Today", original_release_year=1978),
        Album(5, 4, "Soprano Sax", original_release_year=1976),
        Album(6, 5, "Raw Power", original_release_year=1973),
        Album(7, 5, "Fun House", original_release_year=1970),
        Album(8, 6, "B Side", original_release_year=2021, style_ids=[1]),
        Album(9, 6, "A Side", original_release_year=2021, style_ids=[1]),
    ]
    assignments = [
        ArtistClusterAssignment(1, 1, True),
        ArtistClusterAssignment(3, 1, True),
        ArtistClusterAssignment(4, 1, True),
        ArtistClusterAssignment(5, 2, True),
    ]
    units = build_units(
        artists, albums, assignments, [AliasGroup(1, "Chet Baker")], [Style(1, "Garage", 2)]
    )

    ordered = order_albums(units, albums, clusters)

    assert [(o.album_id, o.band) for o in ordered] == [
        # Rock comes first; the new band's cluster is proposed from its style.
        (7, "1960s"), (6, "1960s"), (9, "2020s+"), (8, "2020s+"),
        # Jazz: one band, units alphabetically; the family is one unit sorted by year.
        (4, "before 1960"), (2, "before 1960"), (1, "before 1960"), (3, "before 1960"),
        (5, "before 1960"),
    ]
    by_name = {unit.name: unit for unit in units}
    assert by_name["chet baker"].artist_ids == (1, 2)
    assert (by_name["new band"].cluster_id, by_name["new band"].cluster_is_proposed) == (2, True)
    # Without a known start, the earliest original year stands in.
    assert by_name["new band"].start_year == 2021


def test_cluster_order_follows_each_clusters_longest_run():
    layout = [3, 1, 3, 3, None, 2, 2, 2, 1, 1, 3]

    assert cluster_order_from_layout(layout) == [3, 2, 1]


def test_only_lps_count_as_lp():
    assert FormatTokens(qualifiers=("2xLP", "Album")).is_lp
    assert not FormatTokens(qualifiers=('12"', "EP")).is_lp
    assert not FormatTokens(qualifiers=('7"', "Single")).is_lp


def test_shelves_are_filled_in_order_and_the_row_runs_on():
    from sleeve_shelf.sorting.placement import Spot, fill_shelves

    albums = [(1, 0.5), (2, 0.5), (3, 1.0), (4, 0.5), (5, 0.5)]

    spots, left_out = fill_shelves(albums, [(10, 1.0), (20, 1.5), (30, 0.5)])

    assert spots == [Spot(1, 10, 0), Spot(2, 10, 1), Spot(3, 20, 0), Spot(4, 20, 1), Spot(5, 30, 0)]
    assert left_out == []


def test_an_album_that_fits_nowhere_is_left_out_without_stopping_the_rest():
    from sleeve_shelf.sorting.placement import fill_shelves

    # The box set is wider than any shelf; the next album still goes where the row was.
    spots, left_out = fill_shelves([(1, 0.5), (2, 3.0), (3, 0.5), (4, 0.5)], [(10, 1.0), (20, 0.5)])

    assert [(s.album_id, s.shelf_id) for s in spots] == [(1, 10), (3, 10), (4, 20)]
    assert left_out == [2]

    # A shelf once passed is not gone back to.
    spots, left_out = fill_shelves([(1, 0.5), (2, 1.0), (3, 0.5)], [(10, 1.0), (20, 1.0)])
    assert [(s.album_id, s.shelf_id) for s in spots] == [(1, 10), (2, 20)]
    assert left_out == [3]


def test_a_location_rule_binds_albums_to_a_cabinet_and_keeps_others_out():
    from sleeve_shelf.sorting.placement import place

    albums = [(1, 0.5, None), (2, 0.5, 9), (3, 0.5, None), (4, 0.5, 9), (5, 0.5, 9)]
    shelves = [(10, 1, 0.5), (20, 9, 1.0), (30, 1, 1.0)]

    spots, left_out = place(albums, shelves)

    # The free albums skip cabinet 9; the bound ones go there and nowhere else.
    assert {(s.album_id, s.shelf_id) for s in spots} == {(1, 10), (3, 30), (2, 20), (4, 20)}
    assert left_out == [5]


def test_records_fetched_before_membership_was_kept_are_fetched_again():
    assert ArtistEnrichment(1, None, None, NOW).member_ids is None
    assert ArtistEnrichment(1, None, None, NOW, member_ids=()).member_ids == ()


def _record(discogs_id, members=(), groups=(), aliases=()):
    return ArtistEnrichment(discogs_id, None, None, datetime(2026, 10, 12), members, groups, aliases)


def test_an_artist_without_a_cluster_takes_that_of_whom_discogs_connects_it_to():
    artists = [
        Artist(1, "Nick Cave", discogs_artist_id=10),
        Artist(2, "Grinderman", discogs_artist_id=20),
        Artist(3, "Warren Ellis", discogs_artist_id=30),
        Artist(4, "Dirty Three", discogs_artist_id=40),
        Artist(5, "Stranger", discogs_artist_id=50),
        Artist(6, "Other Name", discogs_artist_id=60),
    ]
    assignments = [
        ArtistClusterAssignment(1, 7, True),
        ArtistClusterAssignment(3, 8, True),
        # A cluster that was only proposed is no ground to stand on.
        ArtistClusterAssignment(4, 9, False),
    ]
    records = [
        # The band names its members; one of them names the band back, the other does not.
        _record(20, members=(10, 30)),
        _record(10, groups=(20,)),
        _record(40, members=(30,)),
        _record(60, aliases=(30,)),
    ]
    counts = {1: 5, 3: 2}

    hints = clusters_by_connection(artists, assignments, records, counts)

    # Grinderman is shared by two artists: a loose connection, an indication only — the
    # cluster of the member with the most albums.
    assert hints[2] == ClusterHint(7, (1,), decisive=False)
    # Dirty Three is Warren Ellis's own band here, and the other name is his too: close
    # connections, which decide. Nothing is chained on to Grinderman or Nick Cave.
    assert hints[4] == ClusterHint(8, (3,)) and hints[6] == ClusterHint(8, (3,))
    assert hints[4].decisive and hints[6].decisive
    # An artist with a confirmed cluster, or without connections, gets no hint.
    assert set(hints) == {2, 4, 6}


def test_a_sidemans_bands_are_a_loose_connection_and_a_close_one_goes_before_them():
    artists = [Artist(i, f"Artist {i}", discogs_artist_id=i * 10) for i in range(1, 8)]
    # Artist 1 is in four bands of the collection: a sideman.
    records = [_record(10, groups=(20, 30, 40, 50)), _record(60, groups=(20,)), _record(70, groups=(20,))]
    assignments = [ArtistClusterAssignment(1, 7, True), ArtistClusterAssignment(6, 8, True)]

    hints = clusters_by_connection(artists, assignments, records, {1: 9, 6: 1}, max_bands=3)

    # Band 3 knows only the sideman: an indication.
    assert hints[3] == ClusterHint(7, (1,), decisive=False)
    # Band 2 is shared by the sideman and two others, which makes all of it loose.
    assert hints[2] == ClusterHint(7, (1,), decisive=False)
    # Artist 7 is only connected to a band without a cluster, which gives nothing to go by.
    assert set(hints) == {2, 3, 4, 5}
    # With room for four bands artist 1 is no sideman: a band of his own is close again.
    assert clusters_by_connection(artists, assignments, records, {1: 9, 6: 1})[3].decisive


def test_a_connection_goes_before_the_styles_and_a_curated_cluster_before_both():
    artists = [Artist(1, "Nick Cave"), Artist(2, "Grinderman"), Artist(3, "Unconnected")]
    albums = [
        Album(1, 1, "Tender Prey", style_ids=[1]),
        Album(2, 2, "Grinderman", style_ids=[1]),
        Album(3, 3, "Debut", style_ids=[1]),
    ]
    styles = [Style(1, "Garage Rock", 2)]
    assignments = [ArtistClusterAssignment(1, 7, True)]

    units = {
        unit.name: unit
        for unit in build_units(artists, albums, assignments, [], styles, {1: 9, 2: 7})
    }

    assert (units["nick cave"].cluster_id, units["nick cave"].cluster_is_proposed) == (7, False)
    assert (units["grinderman"].cluster_id, units["grinderman"].cluster_is_proposed) == (7, True)
    assert units["unconnected"].cluster_id == 2


def test_connections_are_read_from_either_record_and_named_by_what_they_are():
    artists = [
        Artist(1, "Nick Cave", discogs_artist_id=10),
        Artist(2, "Grinderman", discogs_artist_id=20),
        Artist(3, "The Birthday Party", discogs_artist_id=30),
        Artist(4, "Nicholas Cave", discogs_artist_id=40),
        Artist(5, "Unnamed On Discogs"),
    ]
    # Grinderman names its member, and one outside the collection; the person names another
    # band; and the other name is only listed on that name's own record.
    records = [_record(20, members=(10, 999)), _record(10, groups=(30,)), _record(40, aliases=(10,))]

    assert connections_of(1, artists, records) == Connections(other_names=(4,), bands=(2, 3))
    assert connections_of(2, artists, records) == Connections(members=(1,))
    assert connections_of(4, artists, records) == Connections(other_names=(1,))
    assert connections_of(5, artists, records) == Connections()


def _spot_case():
    """Shelf 1 holds artist A (albums 1, 2) and B (3), of one cluster and era; shelf 2 holds
    C (4), of that cluster in another era, and D (5), of another cluster."""
    ordered = [
        OrderedAlbum(1, 10, "1960s", "a"),
        OrderedAlbum(11, 10, "1960s", "a"),      # new, by artist A
        OrderedAlbum(16, 10, "1960s", "aa"),     # new artist, sorting inside A's row
        OrderedAlbum(2, 10, "1960s", "a"),
        OrderedAlbum(3, 10, "1960s", "b"),
        OrderedAlbum(12, 10, "1960s", "e"),      # new artist of the same era
        OrderedAlbum(4, 10, "1970s", "c"),
        OrderedAlbum(13, 10, "1980s", "f"),      # new artist of an era no one stands in
        OrderedAlbum(5, 20, "1960s", "d"),
        OrderedAlbum(14, 30, "1960s", "g"),      # new artist of a cluster no one stands in
        OrderedAlbum(15, None, "unknown", "h"),  # no cluster
    ]
    units = {1: "a", 2: "a", 11: "a", 16: "aa", 3: "b", 12: "e", 4: "c", 13: "f", 5: "d", 14: "g", 15: "h"}
    layout = [(1, 1), (2, 1), (3, 1), (4, 2), (5, 2)]
    return ordered, units, layout


def test_a_new_album_goes_next_to_what_it_belongs_with_most_closely():
    ordered, units, layout = _spot_case()

    spots = suggest_spots([11, 12, 13, 14, 15, 16], ordered, units, layout)

    # Among the artist's own albums, by year.
    assert spots[11] == SuggestedSpot(11, 1, 1, 2, "artist")
    # After the last artist of its era that sorts before it; that happens to end the shelf.
    assert spots[12] == SuggestedSpot(12, 1, 3, None, "band")
    # No one of its era stands anywhere: after the last of its cluster.
    assert spots[13] == SuggestedSpot(13, 2, 4, 5, "cluster")
    # No one of its cluster: where the order of the clusters puts it.
    assert spots[14] == SuggestedSpot(14, 2, 5, None, "order")
    # Without a cluster there is nothing to go by.
    assert 15 not in spots
    # It sorts between two albums of artist A, but never goes inside that artist's row.
    assert spots[16] == SuggestedSpot(16, 1, 2, 3, "band")


def test_a_spot_stays_within_the_shelves_a_rule_allows_and_before_what_sorts_after_it():
    ordered, units, layout = _spot_case()

    spots = suggest_spots([12], ordered, units, layout, {12: {2}})

    # Bound to the cabinet of shelf 2, where only a later era of its cluster stands.
    assert spots[12] == SuggestedSpot(12, 2, None, 4, "cluster")
    assert suggest_spots([12], ordered, units, layout, {12: {3}}) == {}


def test_a_few_albums_kept_elsewhere_are_no_place_to_add_to():
    ordered = [OrderedAlbum(i, 10, "1960s", "a") for i in (1, 2, 6, 17)]
    units = {1: "a", 2: "a", 6: "a", 17: "a"}
    # Album 6 of the artist is kept in another cabinet; the new one sorts right after it.
    layout = [(1, 1), (2, 1), (6, 2)]

    assert suggest_spots([17], ordered, units, layout)[17].shelf_id == 2
    home = suggest_spots([17], ordered, units, layout, None, {1: 100, 2: 200})
    assert home[17] == SuggestedSpot(17, 1, 2, None, "artist")


def test_shelf_boundaries_are_chosen_to_keep_albums_where_they_stand():
    from sleeve_shelf.sorting.placement import fill_shelves, fill_shelves_keeping

    albums = [(i, 1.0) for i in range(1, 9)]
    shelves = [(10, 4.0), (20, 4.0), (30, 4.0)]
    # Today shelf 10 holds 1-3, 20 holds 4-6, 30 holds 7-8: filling to the brim would
    # push 4 onto shelf 10, and everything after it along.
    standing = {1: 10, 2: 10, 3: 10, 4: 20, 5: 20, 6: 20, 7: 30, 8: 30}

    greedy, _ = fill_shelves(albums, shelves)
    calm, left_out = fill_shelves_keeping(albums, shelves, standing)

    assert sum(standing[s.album_id] == s.shelf_id for s in greedy) == 5
    assert [(s.album_id, s.shelf_id, s.position) for s in calm] == [
        (1, 10, 0), (2, 10, 1), (3, 10, 2), (4, 20, 0), (5, 20, 1), (6, 20, 2), (7, 30, 0), (8, 30, 1),
    ]
    assert left_out == []


def test_keeping_albums_in_place_never_leaves_more_out_and_keeps_the_order():
    from sleeve_shelf.sorting.placement import fill_shelves, fill_shelves_keeping

    albums = [(1, 0.5), (2, 3.0), (3, 0.5), (4, 0.5), (5, 0.5)]
    shelves = [(10, 1.0), (20, 1.0)]
    # Nothing stands anywhere yet: the order and what is left out are those of filling to the brim.
    greedy, greedy_left = fill_shelves(albums, shelves)
    calm, calm_left = fill_shelves_keeping(albums, shelves, {})

    assert calm_left == greedy_left == [2]
    assert [s.album_id for s in calm] == [s.album_id for s in greedy] == [1, 3, 4, 5]
