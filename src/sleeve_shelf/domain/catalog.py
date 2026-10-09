"""Collection entities: artists, albums, and the style/cluster taxonomy."""

import re
from dataclasses import dataclass, field

_LP = re.compile(r"^(?:\d+x)?LP$")


@dataclass(slots=True)
class AliasGroup:
    """An artist family: billings and side projects that stand together on the shelf."""

    id: int
    label: str


@dataclass(frozen=True, slots=True)
class FamilyDismissal:
    """A suggested family around this artist that the user turned down."""

    anchor_artist_id: int


@dataclass(slots=True)
class Artist:
    """An artist in the collection, optionally a member of an alias group."""

    id: int
    name: str
    alias_group_id: int | None = None
    start_year: int | None = None


@dataclass(slots=True)
class Cluster:
    """A user-curated grouping of styles, decoupled from the Discogs taxonomy."""

    id: int
    name: str
    # Place in the curated sequence of clusters across the shelves.
    position: int | None = None


@dataclass(slots=True)
class Style:
    """A Discogs style, mapped to the cluster it belongs to."""

    id: int
    name: str
    cluster_id: int


@dataclass(frozen=True, slots=True)
class WidthConstants:
    """Width-estimation figures in cm, as configured in config.yaml."""

    base_per_disc: float
    surcharge_180_gram_per_disc: float
    surcharge_gatefold: float


@dataclass(frozen=True, slots=True)
class FormatTokens:
    """What was parsed from the format of a release: the CSV's Format field or the API's formats."""

    disc_count: int = 1
    is_180_gram: bool = False
    is_gatefold: bool = False
    is_compound: bool = False
    qualifiers: tuple[str, ...] = ()

    @property
    def is_lp(self) -> bool:
        """Whether this is an LP rather than a single or EP (7", 10", 12")."""
        return any(_LP.match(token) for token in self.qualifiers)

    def estimated_width_cm(self, constants: WidthConstants) -> float:
        """Estimate the shelf width; compound formats only get the rough fallback."""
        width = self.disc_count * constants.base_per_disc
        if self.is_compound:
            return width
        if self.is_180_gram:
            width += self.disc_count * constants.surcharge_180_gram_per_disc
        if self.is_gatefold:
            width += constants.surcharge_gatefold
        return width


@dataclass(slots=True)
class Album:
    """A vinyl release owned in the collection.

    An album seeded by the initial load has only artist and title; the Discogs
    fields stay None until it is matched to a release.
    """

    id: int
    artist_id: int
    title: str
    release_id: int | None = None
    format_tokens: FormatTokens | None = None
    computed_width_cm: float | None = None
    master_id: int | None = None
    original_release_year: int | None = None
    manual_width_cm: float | None = None
    width_confirmed: bool = True
    style_ids: list[int] = field(default_factory=list)
    era_band_id: int | None = None
    cover_url: str | None = None
    # The same cover as a large image, only fetched when the cover is enlarged.
    cover_image_url: str | None = None
    # False while the year may still be that of the pressing rather than the original.
    original_year_confirmed: bool = False
    # True when the last sync or import no longer found the release in the Discogs collection.
    left_discogs: bool = False

    @property
    def width_cm(self) -> float | None:
        """The width used for placement: the manual value overrides the computed one."""
        if self.manual_width_cm is not None:
            return self.manual_width_cm
        return self.computed_width_cm
