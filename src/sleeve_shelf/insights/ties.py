"""What ties artists together, read from what Discogs lists.

The kinds of tie, who is on the record of an album, when two songs are one, and which labels count.
No storage in here.
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistEnrichment,
    ReleaseEnrichment,
    WRITER_ROLE,
    artists_by_discogs_id,
    credits_by_release,
    plain_name,
    sort_name,
)


class Tie(StrEnum):
    """What ties two artists, the closest first: a line is drawn as its closest tie."""

    # Another name of the same artist, as Discogs lists it.
    NAME = "name"
    # A person and a band the person is in, as Discogs lists it.
    MEMBER = "member"
    # One artist's name inside the other's: "Chet Baker Quartet" and "Chet Baker".
    BILLING = "billing"
    # Both in one family.
    FAMILY = "family"
    # One credited on an album of the other: a musician, an arranger, a producer.
    CREDIT = "credit"
    # A musician without an album in the collection, on albums of an artist.
    SESSION = "session"
    # The same song on albums of both.
    SONGS = "songs"
    # Albums of both on one record label: of the pressing, so a reissue label counts too.
    LABEL = "label"


# Ties that say two artists share something, rather than that they know each other.
LOOSE_TIES = frozenset({Tie.SONGS, Tie.LABEL})


# Discogs' own entry for what came out without a label.
NO_LABEL = "not on label"


# A musician without an album of their own is a point in the network from this many albums.
MUSICIAN_ALBUMS = 5


def on_the_record(role: str) -> tuple[str, ...]:
    """The parts of a Discogs role that put someone on the record.

    Remarks between brackets are left out: "Piano [Grand], Liner Notes" is ("Piano",). Who wrote a
    song is not on the record for it: writing "Yesterdays" does not tie Jerome Kern to all who
    recorded it.

    Args:
        role: The role as Discogs words it.

    Returns:
        The parts that count.
    """
    found = []
    for part in re.split(r",\s*(?![^\[]*\])", role):
        part = re.sub(r"\s*\[[^\]]*\]", "", part).strip()
        if not part or WRITER_ROLE.search(part) or _LOOKED_BACK.search(part):
            continue
        if _MAKES_THE_MUSIC.search(part) or not _BEHIND_THE_RECORD.search(part):
            found.append(part)
    return tuple(found)


def named_in(name: str, album_artist: str) -> bool:
    """Whether the credited person is named on the record itself.

    Nick Cave on an album of Nick Cave & The Bad Seeds is no sideman.

    Args:
        name: The name as credited.
        album_artist: The artist of the album.

    Returns:
        True when the one name stands in the other, as whole words.
    """
    found, billed = sort_name(name), sort_name(album_artist)
    # Only for a name that occurs at all is a pattern made: there are thousands of credits.
    return bool(found) and found in billed and re.search(r"(?<!\w)" + re.escape(found) + r"(?!\w)", billed) is not None


def is_various(artist: Artist) -> bool:
    """Whether the artist is Discogs' "Various", of compilations.

    Args:
        artist: The artist.

    Returns:
        True for "Various".
    """
    return artist.discogs_artist_id == _VARIOUS_DISCOGS_ID or artist.name.casefold() in _VARIOUS_NAMES


def song_key(title: str) -> str:
    """A song title as songs are compared.

    Without what stands between brackets at its end, accents, punctuation, case, and a leading
    "The": "'Round Midnight (Take 2)" is "round midnight". Brackets at the start belong to the
    title: "(Dance With The) Guitar Man" is another song than "Guitar Man".

    Args:
        title: The title.

    Returns:
        The title as compared.
    """
    # A title that is all brackets ("(Nice Dream)") keeps them.
    while (shorter := _TRAILING_BRACKETS.sub("", title)) != title and shorter.strip():
        title = shorter
    title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().casefold()
    title = " ".join(re.sub(r"[^a-z0-9]+", " ", title).split())
    return title.removeprefix("the ")


@dataclass(frozen=True, slots=True)
class OnRecord:
    """An artist of the collection credited on an album of another.

    Attributes:
        album_id: The album.
        album_title: Its title.
        album_artist_id: The artist the album is of.
        artist_id: The artist credited on it.
        name: The name of the artist credited.
        roles: What for.
    """

    album_id: int
    album_title: str
    album_artist_id: int
    artist_id: int
    name: str
    roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Heard:
    """A song on an album.

    Attributes:
        album_id: The album.
        artist_id: The artist of the album.
        title: The title on this album.
        writers: Who wrote it, as Discogs ids.
    """

    album_id: int
    artist_id: int
    title: str
    writers: frozenset[int]


def collection_songs(artists: list[Artist], albums: list[Album], releases: list[ReleaseEnrichment]) -> list[tuple[str, list[Heard]]]:
    """The songs of the collection, each as its key and the albums it is on.

    One title can be several songs: two tracks of the same title are one song when Discogs names a
    writer of both (Kern's "Yesterdays" is not Guns N' Roses'). A track without a writer belongs to
    its title's song only when the tracks with one are all one song; with none known at all, the
    title alone decides. A compilation ("Various") counts for no one.

    Args:
        artists: All artists.
        albums: All albums.
        releases: The cached releases.

    Returns:
        Per song its key and where it is heard.
    """
    various = {artist.id for artist in artists if is_various(artist)}
    tracklists = {release.release_id: release.tracklist or () for release in releases}
    by_key: dict[str, list[Heard]] = {}
    for album in sorted(albums, key=lambda a: a.id):
        if album.artist_id in various:
            continue
        for track in tracklists.get(album.release_id, ()):
            key = song_key(track.title)
            if key not in _NO_SONG:
                heard = Heard(album.id, album.artist_id, track.title, frozenset(track.writers or ()))
                by_key.setdefault(key, []).append(heard)
    songs = []
    for key, heard in by_key.items():
        # Tracks sharing a writer, directly or through another track, are one song.
        groups: list[list[Heard]] = []
        for one in (h for h in heard if h.writers):
            joined = [group for group in groups if any(one.writers & other.writers for other in group)]
            groups = [group for group in groups if not any(group is j for j in joined)]
            groups.append([one, *(other for group in joined for other in group)])
        unknown = [h for h in heard if not h.writers]
        if len(groups) <= 1:
            groups = [(groups[0] if groups else []) + unknown]
        songs += [(key, sorted(group, key=lambda h: h.album_id)) for group in groups]
    return songs


def credited_on_albums(artists: list[Artist], albums: list[Album], releases: list[ReleaseEnrichment]) -> list[OnRecord]:
    """Each artist of the collection on the record of an album of another.

    Once per album with all its roles. A compilation ("Various") counts for no one.

    Args:
        artists: All artists.
        albums: All albums.
        releases: The cached releases.

    Returns:
        One entry per artist and album.
    """
    by_did = artists_by_discogs_id(artists)
    various = {artist.id for artist in artists if is_various(artist)}
    credits = credits_by_release(releases)
    found = []
    for album in sorted(albums, key=lambda a: a.id):
        if album.artist_id in various:
            continue
        roles: dict[int, dict[str, None]] = {}
        for credit in credits.get(album.release_id, ()):
            person = by_did.get(credit.discogs_artist_id)
            if person is None or person.id == album.artist_id or person.id in various:
                continue
            parts = on_the_record(credit.role)
            if parts:
                roles.setdefault(person.id, {}).update(dict.fromkeys(parts))
        names = {a.id: a.name for a in artists if a.id in roles}
        found += [
            OnRecord(album.id, album.title, album.artist_id, person, names[person], tuple(parts))
            for person, parts in sorted(roles.items())
        ]
    return found


@dataclass(frozen=True, slots=True)
class SidePlayer:
    """Someone who plays or sings on an album without it being theirs, once per album.

    Attributes:
        album_id: The album.
        album_title: Its title.
        album_artist_id: The artist the album is of.
        discogs_id: The person on Discogs.
        name: The name as credited.
        roles: What for.
    """

    album_id: int
    album_title: str
    album_artist_id: int
    discogs_id: int
    name: str
    roles: tuple[str, ...]


def side_players(
    artists: list[Artist], albums: list[Album], artist_records: list[ArtistEnrichment], releases: list[ReleaseEnrichment]
) -> list[SidePlayer]:
    """Who plays or sings on the albums of others.

    Not a producer, who is not at the instrument; not anyone named on the record itself, nor a
    member Discogs lists of the album's band, nor anyone on a compilation.

    Args:
        artists: All artists.
        albums: All albums.
        artist_records: The cached artist records.
        releases: The cached releases.

    Returns:
        One entry per person and album.
    """
    by_id = {artist.id: artist for artist in artists}
    members = {record.discogs_artist_id: set(record.member_ids or ()) for record in artist_records}
    credits = credits_by_release(releases)
    found = []
    for album in sorted(albums, key=lambda a: a.id):
        owner = by_id.get(album.artist_id)
        if owner is None or is_various(owner):
            continue
        band = members.get(owner.discogs_artist_id, ())
        roles: dict[int, dict[str, None]] = {}
        names: dict[int, str] = {}
        for credit in credits.get(album.release_id, ()):
            person = credit.discogs_artist_id
            if person == owner.discogs_artist_id or person in band or named_in(credit.name, owner.name):
                continue
            parts = [part for part in on_the_record(credit.role) if not _PRODUCER.search(part)]
            if parts:
                roles.setdefault(person, {}).update(dict.fromkeys(parts))
                names[person] = plain_name(credit.name)
        found += [
            SidePlayer(album.id, album.title, album.artist_id, person, names[person], tuple(parts))
            for person, parts in sorted(roles.items())
        ]
    return found


def musicians_as_points(players: list[SidePlayer], artists: list[Artist]) -> set[int]:
    """Those on enough albums to be a point of their own, without being an artist in the collection.

    Args:
        players: Who plays on which album.
        artists: All artists.

    Returns:
        Their Discogs ids.
    """
    known = {artist.discogs_artist_id for artist in artists}
    on_albums = Counter(player.discogs_id for player in players if player.discogs_id not in known)
    return {person for person, count in on_albums.items() if count >= MUSICIAN_ALBUMS}


def labels_of_albums(
    artists: list[Artist], albums: list[Album], releases: list[ReleaseEnrichment], left_out: Iterable[str] = ()
) -> dict[int, dict[int, str]]:
    """Per album the labels that can tie artists.

    No "Not On Label", no compilation, and none of those left out, whichever way Discogs spells it
    ("Sam Records (8)").

    Args:
        artists: All artists.
        albums: All albums.
        releases: The cached releases.
        left_out: Labels that tie no one.

    Returns:
        Per album id its labels' names, by Discogs id.
    """
    various = {artist.id for artist in artists if is_various(artist)}
    of_release = {release.release_id: release.labels or () for release in releases}
    without = {sort_name(name) for name in left_out}
    on_album: dict[int, dict[int, str]] = {}
    for album in albums:
        if album.artist_id in various:
            continue
        for label in of_release.get(album.release_id, ()):
            if not label.name.casefold().startswith(NO_LABEL) and sort_name(label.name) not in without:
                on_album.setdefault(album.id, {})[label.discogs_label_id] = label.name
    return on_album


_PRODUCER = re.compile(r"produc", re.IGNORECASE)


# Song titles that say nothing about the song, so two albums having one ties no one.
_NO_SONG = frozenset(
    {
        "",
        "intro",
        "introduction",
        "interlude",
        "outro",
        "theme",
        "the theme",
        "finale",
        "prelude",
        "reprise",
        "medley",
        "untitled",
        "silence",
        "hidden track",
        "vocal",
        "instrumental",
    }
)


# Discogs' artist for a compilation: its songs are by many artists, so it shares none.
_VARIOUS_DISCOGS_ID = 194


_VARIOUS_NAMES = frozenset({"various", "various artists"})


# What stands between brackets at the end of a title: "(Live)", "(Take 2)", "[Bonus Track]".
_TRAILING_BRACKETS = re.compile(r"\s*(\([^()]*\)|\[[^\[\]]*\])\s*$")


# Who is on the record: everyone credited but those behind it. Instruments and voices are too
# many to name, so what does not count is named instead.
_LOOKED_BACK = re.compile(r"executive|reissue|re-issue|compilation", re.IGNORECASE)


_MAKES_THE_MUSIC = re.compile(r"conduct|music(al)? direct|arrang|produc", re.IGNORECASE)


_BEHIND_THE_RECORD = re.compile(
    r"design|photo|liner|master(ed|ing)|lacquer|engineer|\bart\b|artwork|layout|cover|\bmix|recorded"
    r"|cut by|pressed|copyright|phonographic|manufactur|distribut|management|coordinat|illustrat"
    r"|typograph|sleeve|graphic|transfer|a&r|compiled|booking|legal|notes|edited|editor|technician"
    r"|tape|programm|research|supervis|lettering|painting|text by|translated|concept|^other|film"
    r"|video|direct|published|licensed|marketed|crew|assistant|consultant|restor|sound|overdub"
    r"|tuner|tuned|lighting|interview|dedicat|thanks|presenter|announcer",
    re.IGNORECASE,
)
