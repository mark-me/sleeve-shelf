"""Parsing of the free-text Discogs Format field, e.g. '2xLP, Album, RE, 180 + CD'."""

import re
from dataclasses import dataclass

from sleeve_shelf.domain import FormatTokens

# A vinyl medium, optionally with a quantity: LP, 2xLP, 7", 2x12", ...
_VINYL = re.compile(r'^(?:(\d+)x)?(?:LP|7"|10"|12")$')


@dataclass(frozen=True, slots=True)
class ParsedFormat:
    is_vinyl: bool
    tokens: FormatTokens


def parse_format(text: str, count_bonus_discs_as_vinyl: bool = True) -> ParsedFormat:
    """Detect vinyl and extract the width-relevant tokens.

    A format is a list of '+'-separated segments, each starting with its medium.
    With count_bonus_discs_as_vinyl any vinyl segment makes the release vinyl
    (so 'CD + LP' counts); without it the first medium has to be vinyl.
    """
    segments = [
        [token.strip() for token in segment.split(",") if token.strip()]
        for segment in text.split("+")
    ]
    segments = [segment for segment in segments if segment]
    tokens = tuple(token for segment in segments for token in segment)
    vinyl_discs = [
        int(match.group(1) or 1)
        for segment in segments
        if (match := _VINYL.match(segment[0]))
    ]
    if count_bonus_discs_as_vinyl:
        is_vinyl = bool(vinyl_discs)
    else:
        # A box is packaging, not a medium, so look past it.
        media = [segment for segment in segments if segment[0] != "Box"]
        is_vinyl = bool(media) and _VINYL.match(media[0][0]) is not None
    return ParsedFormat(
        is_vinyl=is_vinyl,
        tokens=FormatTokens(
            disc_count=sum(vinyl_discs) or 1,
            is_180_gram="180" in tokens,
            is_gatefold="Gat" in tokens,
            is_compound="+" in text or "Box" in tokens,
            qualifiers=tokens,
        ),
    )
