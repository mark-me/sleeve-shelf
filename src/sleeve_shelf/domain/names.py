"""Names as they are compared and shown: Discogs tells apart people of one name with a "(2)"."""

import re


def sort_name(name: str) -> str:
    """A name as it is compared and sorted.

    Without Discogs' "(2)" suffix, case-insensitive, and with any run of spaces as one. The suffix
    goes first and the spaces after, rather than in one pattern with a leading whitespace match,
    which takes quadratic time on a long run of spaces — and a search text typed by a user passes
    through here.

    Args:
        name: The name.

    Returns:
        The name as compared.
    """
    return " ".join(re.sub(r"\(\d+\)", "", name).casefold().split())


def plain_name(name: str) -> str:
    """A name without Discogs' "(3)", which tells apart people of one name on Discogs only.

    Args:
        name: The name as Discogs gives it.

    Returns:
        The name as shown.
    """
    return re.sub(r"\s*\(\d+\)$", "", name)
