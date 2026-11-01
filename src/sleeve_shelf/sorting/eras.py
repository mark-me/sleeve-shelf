"""Era bands: fixed decades of the year an artist began."""

UNKNOWN = "unknown"
BEFORE_1960 = "before 1960"
FROM_2020 = "2020s+"

# Oldest first; an unknown start year sorts last.
BANDS = (BEFORE_1960, "1960s", "1970s", "1980s", "1990s", "2000s", "2010s", FROM_2020, UNKNOWN)


def band_of(start_year: int | None) -> str:
    """The band a start year falls in.

    Args:
        start_year: The year; None for an artist without one.

    Returns:
        The band.
    """
    if not start_year:
        return UNKNOWN
    if start_year < 1960:
        return BEFORE_1960
    if start_year >= 2020:
        return FROM_2020
    return f"{start_year // 10 * 10}s"


def band_index(band: str) -> int:
    """The place of a band among the bands, oldest first.

    Args:
        band: The band.

    Returns:
        Its place.
    """
    return BANDS.index(band)
