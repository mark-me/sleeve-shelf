"""Reader for the Discogs collection CSV export."""

import csv
from dataclasses import dataclass
from pathlib import Path

from sleeve_shelf.domain import FormatTokens
from sleeve_shelf.ingestion.formats import parse_format

REQUIRED_COLUMNS = ("Artist", "Title", "Format", "release_id")


@dataclass(frozen=True, slots=True)
class CollectionItem:
    """One release owned, vinyl or not: a row of the export or a release from the API.

    Attributes:
        release_id: The release.
        artist: The artist.
        title: The title.
        is_vinyl: Whether it is vinyl.
        format_tokens: What its format says.
        cover_url: Only the API gives a cover; the export has none.
        cover_image_url: The same cover as a large image.
        artist_discogs_id: Only the API names the artist on Discogs, and only for a release credited
            to one artist.
    """

    release_id: int
    artist: str
    title: str
    is_vinyl: bool
    format_tokens: FormatTokens
    cover_url: str | None = None
    cover_image_url: str | None = None
    artist_discogs_id: int | None = None


def read_collection(
    path: str | Path, count_bonus_discs_as_vinyl: bool = True
) -> list[CollectionItem]:
    """Read every row of the export; the caller filters on is_vinyl.

    Args:
        path: The CSV file.
        count_bonus_discs_as_vinyl: Whether a vinyl disc anywhere in a release makes it vinyl.

    Returns:
        One item per row.

    Raises:
        ValueError: The file lacks a column it needs.
    """
    with open(path, encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        missing = [name for name in REQUIRED_COLUMNS if name not in (reader.fieldnames or ())]
        if missing:
            raise ValueError(f"The export is missing columns: {', '.join(missing)}")
        items = []
        for row in reader:
            if not (row["release_id"] or "").strip().isdigit():
                continue
            parsed = parse_format(row["Format"] or "", count_bonus_discs_as_vinyl)
            items.append(
                CollectionItem(
                    release_id=int(row["release_id"]),
                    artist=(row["Artist"] or "").strip(),
                    title=(row["Title"] or "").strip(),
                    is_vinyl=parsed.is_vinyl,
                    format_tokens=parsed.tokens,
                )
            )
    return items
