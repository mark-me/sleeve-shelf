"""Artist families: suggesting which artists are billings or projects of the same artist."""

import re
from dataclasses import dataclass

from sleeve_shelf.domain import Artist


@dataclass(frozen=True, slots=True)
class FamilySuggestion:
    """An artist whose name appears inside the names of the other members."""

    anchor_id: int
    member_ids: tuple[int, ...]


def sort_name(name: str) -> str:
    """A name as it is compared and sorted: without Discogs' "(2)" suffix, case-insensitive."""
    return re.sub(r"\s*\(\d+\)", "", name).casefold().strip()


def suggest_families(
    artists: list[Artist], dismissed_anchor_ids: frozenset[int] | set[int] = frozenset()
) -> list[FamilySuggestion]:
    """Suggest a family around every ungrouped artist whose name others contain.

    "Chet Baker" gathers "Chet Baker Quartet" and "Chet Baker & Crew". An artist
    naming several others ("Duke Ellington & John Coltrane") goes to the one named
    first. Artists already in a family, and anchors the user dismissed, are left out.
    """
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
        if anchor_id not in dismissed_anchor_ids
    ]
