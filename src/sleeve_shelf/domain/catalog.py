"""Collection entities: artists, albums, and the style/cluster taxonomy."""

import re
from dataclasses import dataclass, field
from datetime import date

_LP = re.compile(r"^(?:\d+x)?LP$")


@dataclass(slots=True)
class AliasGroup:
    """An artist family: billings and side projects that stand together on the shelf.

    Attributes:
        id: The family's id.
        label: The family's name.
    """

    id: int
    label: str


@dataclass(frozen=True, slots=True)
class UnrelatedArtists:
    """Two artists the user says are not related, though one name stands inside the other.

    Moondog Jr. took his name from Moondog.

    Attributes:
        one: The lower of the two artist ids.
        other: The higher of the two artist ids.
    """

    one: int
    other: int


@dataclass(frozen=True, slots=True)
class FamilyDismissal:
    """A suggested family around this artist that the user turned down.

    Attributes:
        anchor_artist_id: The artist the suggestion was named after.
    """

    anchor_artist_id: int


@dataclass(slots=True)
class Artist:
    """An artist in the collection, optionally a member of an alias group.

    Attributes:
        id: The artist's id.
        name: The name as it stands on the shelf or on Discogs.
        alias_group_id: The family the artist belongs to, if any.
        start_year: The year the artist began, if known; it decides the era band.
        discogs_artist_id: The artist on Discogs, as a sync found it on the artist's releases.
        picture_file: The file of a picture the user added, in the data directory; it goes before
            Discogs' own.
    """

    id: int
    name: str
    alias_group_id: int | None = None
    start_year: int | None = None
    discogs_artist_id: int | None = None
    picture_file: str | None = None


@dataclass(slots=True)
class Cluster:
    """A user-curated grouping of styles, decoupled from the Discogs taxonomy.

    Attributes:
        id: The cluster's id.
        name: The cluster's name.
        position: Place in the curated sequence of clusters across the shelves.
    """

    id: int
    name: str
    position: int | None = None


@dataclass(slots=True)
class Style:
    """A Discogs style, mapped to the cluster it belongs to.

    Attributes:
        id: The style's id.
        name: The style as Discogs names it.
        cluster_id: The cluster it belongs to.
    """

    id: int
    name: str
    cluster_id: int


@dataclass(frozen=True, slots=True)
class WidthConstants:
    """Width-estimation figures in cm, as configured in config.yaml.

    Attributes:
        base_per_disc: The width of one disc.
        surcharge_180_gram_per_disc: What 180 gram adds per disc.
        surcharge_gatefold: What a gatefold sleeve adds.
    """

    base_per_disc: float
    surcharge_180_gram_per_disc: float
    surcharge_gatefold: float


@dataclass(frozen=True, slots=True)
class FormatTokens:
    """What was parsed from the format of a release: the CSV's Format field or the API's formats.

    Attributes:
        disc_count: The number of discs.
        is_180_gram: Whether the discs are 180 gram.
        is_gatefold: Whether the sleeve is a gatefold.
        is_compound: Whether it is a box set or bundle, whose width can only be estimated roughly.
        qualifiers: The terms of the format as Discogs gives them.
    """

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
        """Estimate the shelf width; compound formats only get the rough fallback.

        Args:
            constants: The width figures to go by.

        Returns:
            The estimated width in cm.
        """
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

    An album seeded by the initial load has only artist and title; the Discogs fields stay None
    until it is matched to a release.

    Attributes:
        id: The album's id.
        artist_id: The artist it belongs to.
        title: The title.
        release_id: The release on Discogs, once linked.
        format_tokens: What its format says, once known.
        computed_width_cm: The width estimated from the format.
        master_id: The master release on Discogs, once fetched.
        original_release_year: The year the album first came out, or that of the pressing until the
            master is known.
        manual_width_cm: The width as measured, which overrides the estimate.
        width_confirmed: False while the width is only a rough estimate, as for a box set.
        style_ids: Its styles.
        era_band_id: The era band of its artist it falls in.
        cover_url: The cover as a small image.
        cover_image_url: The same cover as a large image, only fetched when the cover is enlarged.
        original_year_confirmed: False while the year may still be that of the pressing rather than
            the original.
        left_discogs: True when the last sync or import no longer found the release in the Discogs
            collection.
        kept_after_discogs: True when the user keeps the album although it left Discogs, and is not
            to be asked again.
        new_purchase: True for an album a sync or import added to an artist whose cluster was
            already confirmed, until it has been weighed against that cluster (see
            shelving/shifts.py).
        added_on: The day a sync or import added the album; None for one that came with the
            workbook.
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
    cover_image_url: str | None = None
    original_year_confirmed: bool = False
    left_discogs: bool = False
    kept_after_discogs: bool = False
    new_purchase: bool = False
    added_on: date | None = None

    @property
    def width_cm(self) -> float | None:
        """The width used for placement: the manual value overrides the computed one."""
        if self.manual_width_cm is not None:
            return self.manual_width_cm
        return self.computed_width_cm


def clusters_in_order(clusters: list[Cluster]) -> list[Cluster]:
    """The clusters in their curated order; those without a position come after, by id.

    Args:
        clusters: The clusters, in any order.

    Returns:
        The clusters in order.
    """
    return sorted(clusters, key=lambda c: (c.position is None, c.position or 0, c.id))


def artists_by_discogs_id(artists: list[Artist]) -> dict[int, Artist]:
    """The artists Discogs knows, by their Discogs id.

    Args:
        artists: The artists, those without a Discogs id among them.

    Returns:
        The artists with a Discogs id, by that id.
    """
    return {a.discogs_artist_id: a for a in artists if a.discogs_artist_id is not None}


def artist_ids_by_discogs_id(artists: list[Artist]) -> dict[int, int]:
    """The ids of the artists Discogs knows, by their Discogs id.

    Args:
        artists: The artists, those without a Discogs id among them.

    Returns:
        The ids of the artists with a Discogs id, by that id.
    """
    return {a.discogs_artist_id: a.id for a in artists if a.discogs_artist_id is not None}
