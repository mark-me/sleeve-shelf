"""Artist families: suggesting which artists are billings or projects of the same artist."""

import re
from dataclasses import dataclass

from sleeve_shelf.domain import Artist, ArtistEnrichment

# A person in more bands of the collection than this is a sideman: those bands do not
# belong together because of that one person.
MAX_BANDS = 3


@dataclass(frozen=True, slots=True)
class FamilySuggestion:
    """Artists that belong with the anchor, which a new family is named after."""

    anchor_id: int
    member_ids: tuple[int, ...]
    # Set when the suggestion is to add the members to this existing family, not to make one.
    # The anchor is then the artist of that family with the lowest id.
    group_id: int | None = None
    # Where the suggestion comes from: "names" (one name inside the other) or "discogs"
    # (Discogs lists the artists as member, group or other name of each other).
    source: str = "names"


def sort_name(name: str) -> str:
    """A name as it is compared and sorted: without Discogs' "(2)" suffix, case-insensitive."""
    return re.sub(r"\s*\(\d+\)", "", name).casefold().strip()


def suggest_families(
    artists: list[Artist],
    dismissed_ids: frozenset[int] | set[int] = frozenset(),
    enrichments: list[ArtistEnrichment] | None = None,
    album_counts: dict[int, int] | None = None,
) -> list[FamilySuggestion]:
    """Suggest families from the artist names and from who Discogs says belongs together.

    From the names: "Chet Baker" gathers "Chet Baker Quartet" and "Chet Baker & Crew"; an
    artist naming several others ("Duke Ellington & John Coltrane") goes to the one named
    first. From Discogs: the other names of one artist, and a person with the bands that
    person is in. Whatever the user turned down is left out: a new family by the artist it
    would be named after, an addition to an existing family by the artist to add.
    """
    by_name = _families_from_names(artists, dismissed_ids)
    return by_name + _families_from_discogs(
        artists, dismissed_ids, enrichments or [], by_name, album_counts or {}
    )


def _families_from_names(
    artists: list[Artist], dismissed_ids: frozenset[int] | set[int]
) -> list[FamilySuggestion]:
    """Families that the artist names reveal: one name inside the other."""
    free = [artist for artist in artists if artist.alias_group_id is None]
    names = {artist.id: sort_name(artist.name) for artist in free}
    patterns = {
        artist_id: re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)")
        for artist_id, name in names.items()
        if name
    }

    anchor_of: dict[int, int] = {}
    for artist_id, name in names.items():
        found = [
            (match.start(), -len(names[other_id]), other_id)
            for other_id, pattern in patterns.items()
            if names[other_id] != name and (match := pattern.search(name))
        ]
        if found:
            anchor_of[artist_id] = min(found)[2]

    members: dict[int, list[int]] = {}
    for artist_id, anchor_id in anchor_of.items():
        # Follow "The Miles Davis Quintet Together With ..." up to "Miles Davis".
        while anchor_id in anchor_of:
            anchor_id = anchor_of[anchor_id]
        members.setdefault(anchor_id, []).append(artist_id)

    return [
        FamilySuggestion(anchor_id, tuple(sorted(member_ids, key=lambda i: names[i])))
        for anchor_id, member_ids in sorted(members.items(), key=lambda item: names[item[0]])
        if anchor_id not in dismissed_ids
    ]


def _families_from_discogs(
    artists: list[Artist],
    dismissed_ids: frozenset[int] | set[int],
    enrichments: list[ArtistEnrichment],
    by_name: list[FamilySuggestion],
    album_counts: dict[int, int],
) -> list[FamilySuggestion]:
    """Families that names cannot reveal: who Discogs lists as member, group or other name.

    Nothing is chained: a family is one artist under all its names, with the bands that
    artist is in. A band of two artists in the collection belongs to neither, and a
    sideman draws no band in.
    """
    by_did = {a.discogs_artist_id: a for a in artists if a.discogs_artist_id is not None}
    records = [e for e in enrichments if e.discogs_artist_id in by_did]
    name_of = {a.id: sort_name(a.name) for a in artists}

    def in_collection(discogs_ids: tuple[int, ...] | None) -> list[int]:
        return [by_did[d].id for d in discogs_ids or () if d in by_did]

    # Other names of one artist count as that one artist: same_as leads to one of them.
    same_as = {a.id: a.id for a in by_did.values()}

    def root(artist_id: int) -> int:
        while same_as[artist_id] != artist_id:
            artist_id = same_as[artist_id]
        return artist_id

    bands_of: dict[int, set[int]] = {a.id: set() for a in by_did.values()}
    for entry in records:
        artist_id = by_did[entry.discogs_artist_id].id
        for alias_id in in_collection(entry.alias_ids):
            same_as[root(alias_id)] = root(artist_id)
        for band_id in in_collection(entry.group_ids):
            bands_of[artist_id].add(band_id)
        for member_id in in_collection(entry.member_ids):
            bands_of[member_id].add(artist_id)

    names_of: dict[int, set[int]] = {}
    for artist_id in same_as:
        names_of.setdefault(root(artist_id), set()).add(artist_id)

    # Who a band belongs to: the artists in it that are no sidemen.
    claimed_by: dict[int, set[int]] = {}
    for artist_id, band_ids in bands_of.items():
        band_ids.discard(artist_id)
        if len(band_ids) <= MAX_BANDS:
            for band_id in band_ids:
                claimed_by.setdefault(band_id, set()).add(root(artist_id))

    family_of = {a.id: a.alias_group_id for a in artists if a.alias_group_id is not None}
    taken = {i for suggestion in by_name for i in (suggestion.anchor_id, *suggestion.member_ids)}
    additions: dict[int, set[int]] = {}
    new_families: list[FamilySuggestion] = []
    for person, own_names in sorted(names_of.items(), key=lambda item: name_of[item[0]]):
        bands = {band for band, owners in claimed_by.items() if owners == {person}}
        circle = own_names | bands
        free = {i for i in circle if i not in family_of and i not in taken}
        families = {family_of[i] for i in circle if i in family_of}
        if len(families) > 1:
            continue  # Discogs connects two families: the user's own grouping stands.
        if families:
            free -= set(dismissed_ids)
            if free:
                additions.setdefault(families.pop(), set()).update(free)
                taken |= free
            continue
        candidates = free & own_names
        if len(free) < 2 or not candidates:
            continue
        if candidates & set(dismissed_ids):
            continue
        # Named after the artist, not a band: under the name with the most albums.
        anchor_id = min(candidates, key=lambda i: (-album_counts.get(i, 0), i))
        members = sorted(free - {anchor_id}, key=lambda i: name_of[i])
        new_families.append(FamilySuggestion(anchor_id, tuple(members), None, "discogs"))
        taken |= free

    extensions = [
        FamilySuggestion(
            min(i for i, family in family_of.items() if family == group_id),
            tuple(sorted(member_ids, key=lambda i: name_of[i])),
            group_id,
            "discogs",
        )
        for group_id, member_ids in additions.items()
    ]
    return sorted(extensions + new_families, key=lambda s: name_of[s.anchor_id])
