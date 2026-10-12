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
from sleeve_shelf.sorting.eras import band_of
from sleeve_shelf.sorting.families import suggest_families
from sleeve_shelf.sorting.order import (
    build_units,
    cluster_order_from_layout,
    order_albums,
    propose_cluster,
)

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

    suggestions = suggest_families(artists, enrichments=enrichments, album_counts={5: 3, 4: 1})

    assert [(s.anchor_id, s.member_ids, s.group_id, s.source) for s in suggestions] == [
        # The person anchors the family of his bands, which is named after him.
        (1, (2, 3), None, "discogs"),
        (5, (4,), None, "discogs"),
    ]
    # Turning down the artist a family would be named after settles it.
    assert suggest_families(artists, {1, 5}, enrichments) == []


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
