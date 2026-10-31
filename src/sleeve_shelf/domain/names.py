"""Names as they are compared and shown: Discogs tells apart people of one name with a "(2)"."""

import re


def sort_name(name: str) -> str:
    """A name as it is compared and sorted: without Discogs' "(2)" suffix, case-insensitive,
    and with any run of spaces as one. The suffix goes first and the spaces after, rather
    than in one pattern with a leading \\s*, which takes quadratic time on a long run of
    spaces — and a search text typed by a user passes through here."""
    return " ".join(re.sub(r"\(\d+\)", "", name).casefold().split())


def plain_name(name: str) -> str:
    """A name without Discogs' "(3)", which tells apart people of one name on Discogs only."""
    return re.sub(r"\s*\(\d+\)$", "", name)
