"""Sorting/clustering entities: an artist's cluster, and era bands."""

from dataclasses import dataclass
from enum import StrEnum


class EraBandSource(StrEnum):
    """Where an era band comes from: the sorting engine or the initial load."""

    ALGORITHM = "algorithm"
    INITIAL_LOAD = "initial_load"


@dataclass(slots=True)
class ArtistClusterAssignment:
    """An artist's cluster, either proposed or confirmed.

    Attributes:
        artist_id: The artist.
        cluster_id: The cluster.
        confirmed: Whether the owner confirmed it.
    """

    artist_id: int
    cluster_id: int
    confirmed: bool = False


@dataclass(slots=True)
class EraBand:
    """One band of an artist's discography; albums point at it via era_band_id.

    The label is free text: early/middle/late from the sorting engine, or whatever an initial load
    supplied (e.g. "1990s").

    Attributes:
        id: The band's id.
        artist_id: The artist.
        label: What the band is called.
        position: Its place among the bands of the artist.
        source: Where it comes from.
    """

    id: int
    artist_id: int
    label: str
    position: int
    source: EraBandSource = EraBandSource.ALGORITHM
