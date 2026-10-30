"""Tests for reading Discogs data: the format field, the CSV export, and the API client."""

import json
import urllib.error

import pytest

from sleeve_shelf.domain import Credit, ReleaseLabel, Track
from sleeve_shelf.ingestion.discogs_api import (
    DiscogsClient,
    DiscogsError,
    collection_items,
    credits_of,
    format_text,
    labels_of,
    tracklist,
)
from sleeve_shelf.ingestion.discogs_csv import read_collection
from sleeve_shelf.ingestion.formats import parse_format


@pytest.mark.parametrize(
    ("text", "is_vinyl", "discs"),
    [
        ("LP, Album, RE", True, 1),
        ("2xLP, Album, Gat", True, 2),
        ('7", Single', True, 1),
        ('2x12", Album + CD, Album', True, 2),
        ("CD, Album", False, 1),
        ("DVD-V, NTSC, 4:3", False, 1),
        ("6xCass, Comp + Box", False, 1),
        ("Box, Comp + 4xLP, Album, Ltd", True, 4),
        ("LP + LP, S/Sided + Album, Mono", True, 2),
    ],
)
def test_vinyl_is_detected_from_the_format_text(text, is_vinyl, discs):
    parsed = parse_format(text)

    assert parsed.is_vinyl is is_vinyl
    assert parsed.tokens.disc_count == discs


def test_format_tokens_carry_what_the_width_estimate_needs():
    tokens = parse_format("2xLP, Album, RE, 180, Gat").tokens
    assert (tokens.is_180_gram, tokens.is_gatefold, tokens.is_compound) == (True, True, False)

    assert parse_format("LP, Album + CD").tokens.is_compound
    assert parse_format("3xLP, Comp + Box").tokens.is_compound


def test_bonus_disc_bundles_follow_the_setting():
    assert parse_format("CD, Album + LP").is_vinyl
    assert not parse_format("CD, Album + LP", count_bonus_discs_as_vinyl=False).is_vinyl
    assert parse_format("LP, Album + CD", count_bonus_discs_as_vinyl=False).is_vinyl
    assert parse_format("Box, Comp + 4xLP", count_bonus_discs_as_vinyl=False).is_vinyl


def test_export_rows_are_read_with_quotes_and_non_vinyl(tmp_path):
    export = tmp_path / "collection.csv"
    export.write_text(
        "﻿Catalog#,Artist,Title,Label,Format,Rating,Released,release_id\n"
        '151.102,The Birthday Party,The Bad Seed,4AD,"12"", EP",,1983,1965832\n'
        'CAD 3X03,The National,High Violet ,4AD,"2xLP, Album, 180",,2010,2265783\n'
        'CAD 207 CD,The Birthday Party,Junkyard,4AD,"CD, Album, RE",,1988,395825\n',
        encoding="utf-8",
    )

    items = read_collection(export)

    assert [(i.release_id, i.artist, i.title, i.is_vinyl) for i in items] == [
        (1965832, "The Birthday Party", "The Bad Seed", True),
        (2265783, "The National", "High Violet", True),
        (395825, "The Birthday Party", "Junkyard", False),
    ]
    assert items[1].format_tokens.disc_count == 2


def test_export_without_the_needed_columns_is_refused(tmp_path):
    export = tmp_path / "collection.csv"
    export.write_text("Artist,Title\nTom Waits,Alice\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Format, release_id"):
        read_collection(export)


class _Api:
    """Stands in for the network: answers each request from a queue."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []
        self.slept = []

    def fetch(self, request):
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, int):
            raise urllib.error.HTTPError(request.full_url, answer, "", None, None)
        return json.dumps(answer).encode()

    def client(self):
        return DiscogsClient("secret", fetch=self.fetch, sleep=self.slept.append, clock=lambda: 0)


def test_release_and_master_lookups():
    api = _Api({"styles": ["Folk Rock", "Glam"], "master_id": 32337, "year": 1980}, {"year": 1969})
    client = api.client()

    release = client.release(2918817)
    master = client.master(32337)

    assert (release.styles, release.master_id, release.year) == (("Folk Rock", "Glam"), 32337, 1980)
    assert master.original_release_year == 1969
    assert api.requests[0].full_url == "https://api.discogs.com/releases/2918817"
    assert api.requests[0].get_header("Authorization") == "Discogs token=secret"
    # The second request waits its turn under the rate limit.
    assert api.slept == [pytest.approx(1.05)]


def test_artist_lookup_also_gives_members_groups_and_aliases():
    api = _Api(
        {
            "images": [{"type": "primary", "uri": "https://i.discogs.com/a.jpeg", "uri150": "https://i.discogs.com/a150.jpeg"}],
            "members": [{"id": 101, "name": "Jason Molina", "active": True}, {"id": 102, "name": "Past Member", "active": False}],
            "groups": [{"id": 201, "name": "Songs: Ohia", "active": True}],
            "aliases": [{"id": 301, "name": "Pyramid Electric Co."}],
        },
        {"name": "No Membership"},
        404,
    )
    client = api.client()

    band, plain, gone = client.artist(82294), client.artist(2), client.artist(3)

    # Members and groups are kept as Discogs gives them, former members included.
    assert (band.member_ids, band.group_ids, band.alias_ids) == ((101, 102), (201,), (301,))
    # A record without those lists is complete: there is simply nothing to list.
    assert (plain.member_ids, plain.group_ids, plain.alias_ids) == ((), (), ())
    assert gone.member_ids == ()


def test_a_release_comes_with_its_songs_and_no_headings():
    api = _Api(
        {
            "styles": [],
            "tracklist": [
                {"type_": "heading", "position": "", "title": "Side One"},
                {"type_": "track", "position": "A1", "title": "Ol' '55 ", "duration": "3:58"},
                # A suite listed with its parts counts by its parts.
                {
                    "type_": "index",
                    "position": "",
                    "title": "Medley",
                    "sub_tracks": [
                        {"type_": "track", "position": "B1a", "title": "Part One"},
                        {"type_": "track", "position": "B1b", "title": "Part Two", "duration": ""},
                    ],
                },
                {"type_": "track", "position": "B2", "title": ""},
                {"position": "3", "title": "Without A Type"},
            ],
        },
        404,
    )
    client = api.client()

    # Asked for with their writers: Discogs naming none is an empty list, not an unknown one.
    assert client.release(1).tracklist == (
        Track("A1", "Ol' '55", "3:58", ()),
        Track("B1a", "Part One", None, ()),
        Track("B1b", "Part Two", None, ()),
        Track("3", "Without A Type", None, ()),
    )
    # One that no longer exists has no songs, rather than an unknown tracklist.
    assert client.release(2).tracklist == ()


def test_a_release_comes_with_everyone_it_credits():
    data = {
        "extraartists": [
            {"id": 1, "name": "Bud Powell", "role": "Piano", "tracks": ""},
            {"id": 2, "name": "Rudy Van Gelder", "role": "Engineer", "tracks": "A1 to A3"},
            # No page on Discogs, so nothing to compare it with.
            {"id": 0, "name": "Somebody", "role": "Bass", "tracks": ""},
        ],
        "tracklist": [
            {"position": "A1", "title": "One", "extraartists": [{"id": 3, "name": "Max Roach", "role": "Drums"}]},
            {
                "type_": "index",
                "title": "Suite",
                "extraartists": [{"id": 4, "name": "Gil Evans", "role": "Arranged By"}],
                "sub_tracks": [{"position": "B1a", "title": "Part", "extraartists": [{"id": 5, "name": "Art Pepper", "role": "Alto Saxophone"}]}],
            },
        ],
    }

    assert credits_of(data) == (
        Credit(1, "Bud Powell", "Piano"),
        Credit(2, "Rudy Van Gelder", "Engineer", "A1 to A3"),
        Credit(3, "Max Roach", "Drums", "A1"),
        Credit(4, "Gil Evans", "Arranged By", "B1a"),
        Credit(5, "Art Pepper", "Alto Saxophone", "B1a"),
    )
    assert credits_of({}) == ()


def test_a_release_comes_with_its_labels():
    data = {
        "labels": [
            {"id": 1, "name": "Blue Note ", "catno": "BLP 1501"},
            {"id": 1, "name": "Blue Note", "catno": "BST 1501"},
            {"id": 2, "name": "Liberty"},
            {"id": 0, "name": "No Page"},
        ]
    }

    assert labels_of(data) == (ReleaseLabel(1, "Blue Note", "BLP 1501"), ReleaseLabel(2, "Liberty"))
    assert labels_of({}) == ()


def test_a_fault_on_discogs_side_is_tried_again():
    answers = [urllib.error.HTTPError("u", 500, "fault", None, None), json.dumps({"styles": ["Bop"]}).encode()]
    waited = []

    def fetch(request):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    assert DiscogsClient("t", fetch, waited.append).release(1).styles == ("Bop",)
    assert 5 in waited


def test_a_fault_that_stays_stops_with_its_error():
    def fetch(request):
        raise urllib.error.HTTPError("u", 503, "fault", None, None)

    with pytest.raises(DiscogsError, match="503"):
        DiscogsClient("t", fetch, lambda seconds: None).release(1)


def test_a_song_comes_with_who_wrote_it():
    entries = [
        {"position": "A1", "title": "Yesterdays", "extraartists": [{"id": 11, "role": "Written-By"}, {"id": 99, "role": "Bass"}]},
        {"position": "A2", "title": "Two"},
        {"position": "A3", "title": "Three"},
        {
            "type_": "index",
            "title": "Suite",
            "extraartists": [{"id": 12, "role": "Composed By"}],
            "sub_tracks": [{"position": "B1a", "title": "Part One"}],
        },
    ]
    credits = [
        {"id": 13, "role": "Lyrics By", "tracks": "A2 to A3"},
        {"id": 14, "role": "Music By [Uncredited]", "tracks": "A3, B1a"},
        {"id": 15, "role": "Producer", "tracks": ""},
        {"id": 16, "role": "Songwriter", "tracks": ""},
        # A name Discogs has no page for cannot be compared, so it is left out.
        {"id": 0, "role": "Written-By", "tracks": ""},
    ]

    writers = [track.writers for track in tracklist(entries, credits)]

    # The track's own credits, its suite's, and the release's for the tracks they name or all.
    assert writers == [(11, 16), (13, 16), (13, 14, 16), (12, 14, 16)]


def test_release_without_master_and_missing_release():
    api = _Api({"styles": [], "master_id": 0, "year": 0}, 404)
    client = api.client()

    assert client.release(1).master_id is None
    assert client.release(2).styles == ()


def test_rate_limit_is_waited_out_and_a_bad_token_stops():
    api = _Api(429, {"year": 1969})
    assert api.client().master(1).original_release_year == 1969
    assert 60 in api.slept

    with pytest.raises(DiscogsError, match="token"):
        _Api(401).client().release(1)


def _release(release_id, artists, title, formats):
    return {
        "id": release_id,
        "basic_information": {"title": title, "artists": artists, "formats": formats},
    }


def test_collection_is_fetched_page_by_page_for_the_owner_of_the_token():
    api = _Api(
        {"username": "mark"},
        {"pagination": {"pages": 2}, "releases": [{"id": 1}]},
        {"pagination": {"pages": 2}, "releases": [{"id": 2}]},
    )

    releases = api.client().collection()

    assert [release["id"] for release in releases] == [1, 2]
    assert [request.full_url for request in api.requests] == [
        "https://api.discogs.com/oauth/identity",
        "https://api.discogs.com/users/mark/collection/folders/0/releases?per_page=100&page=1",
        "https://api.discogs.com/users/mark/collection/folders/0/releases?per_page=100&page=2",
    ]


def test_collection_releases_become_the_same_items_as_export_rows():
    items = collection_items(
        [
            _release(
                1,
                [{"name": "Tom Waits", "join": "And"}, {"name": "Crystal Gayle", "join": ""}],
                "One From The Heart ",
                [{"name": "Vinyl", "qty": "1", "descriptions": ["LP", "Album", "Reissue", "Stereo"]}],
            ),
            _release(
                2,
                [{"name": "Stan Getz", "join": ","}, {"name": "João Gilberto", "join": ""}],
                "Getz / Gilberto",
                [
                    {
                        "name": "Vinyl",
                        "qty": "2",
                        "descriptions": ["LP", "Album", "Limited Edition"],
                        "text": "Blue Translucent, Gatefold, 180 gram",
                    }
                ],
            ),
            _release(3, [{"name": "The National"}], "Boxer", [{"name": "CD", "qty": "1", "descriptions": ["Album"]}]),
            _release(
                4,
                [{"name": "Wilco"}],
                "Box",
                [
                    {"name": "Vinyl", "qty": "3", "descriptions": ["LP", "Compilation"]},
                    {"name": "Box Set", "qty": "1", "descriptions": []},
                ],
            ),
        ]
    )

    assert [(i.release_id, i.artist, i.title, i.is_vinyl) for i in items] == [
        (1, "Tom Waits And Crystal Gayle", "One From The Heart", True),
        (2, "Stan Getz, João Gilberto", "Getz / Gilberto", True),
        (3, "The National", "Boxer", False),
        (4, "Wilco", "Box", True),
    ]
    assert items[0].format_tokens.qualifiers == ("LP", "Album", "RE")
    # The export would keep only "Blu" of the free text and miss both.
    gatefold = items[1].format_tokens
    assert (gatefold.disc_count, gatefold.is_180_gram, gatefold.is_gatefold) == (2, True, True)
    assert gatefold.qualifiers == ("2xLP", "Album", "Ltd", "180", "Gat")
    assert (items[3].format_tokens.disc_count, items[3].format_tokens.is_compound) == (3, True)


def test_a_ten_inch_lp_is_named_by_its_size_as_in_the_export():
    assert format_text([{"name": "Vinyl", "qty": "1", "descriptions": ["LP", '10"', "Compilation"]}]) == '10", Comp'


def test_bonus_disc_setting_also_applies_to_the_collection():
    release = _release(
        1,
        [{"name": "Low"}],
        "Hey What",
        [
            {"name": "CD", "qty": "1", "descriptions": ["Album"]},
            {"name": "Vinyl", "qty": "1", "descriptions": ["LP"]},
        ],
    )

    assert collection_items([release])[0].is_vinyl
    assert not collection_items([release], count_bonus_discs_as_vinyl=False)[0].is_vinyl


def test_artist_lookup_takes_the_primary_picture_and_copes_without_one():
    api = _Api(
        {
            "images": [
                {"type": "secondary", "uri": "https://i.discogs.com/b.jpeg", "uri150": "https://i.discogs.com/b150.jpeg"},
                {"type": "primary", "uri": "https://i.discogs.com/a.jpeg", "uri150": "https://i.discogs.com/a150.jpeg"},
            ]
        },
        {"name": "No Picture"},
        404,
    )
    client = api.client()

    pictured, plain, gone = client.artist(82294), client.artist(2), client.artist(3)

    assert (pictured.image_url, pictured.thumb_url) == (
        "https://i.discogs.com/a.jpeg", "https://i.discogs.com/a150.jpeg"
    )
    assert api.requests[0].full_url == "https://api.discogs.com/artists/82294"
    assert (plain.image_url, plain.thumb_url, gone.image_url) == (None, None, None)


def test_only_a_release_of_one_artist_names_that_artist():
    formats = [{"name": "Vinyl", "qty": "1", "descriptions": ["LP"]}]
    items = collection_items(
        [
            _release(1, [{"name": "Tom Waits", "join": "", "id": 82294}], "Closing Time", formats),
            _release(
                2,
                [{"name": "Tom Waits", "join": "And", "id": 82294}, {"name": "Crystal Gayle", "join": "", "id": 5}],
                "One From The Heart",
                formats,
            ),
            _release(3, [{"name": "Various", "join": "", "id": 194}], "Sampler", formats),
        ]
    )

    assert [item.artist_discogs_id for item in items] == [82294, None, None]
