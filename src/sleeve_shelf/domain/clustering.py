"""Sorting/clustering entities: an artist's cluster, and era bands."""

from dataclasses import dataclass
from enum import StrEnum


class EraBandSource(StrEnum):
    ALGORITHM = "algorithm"
    INITIAL_LOAD = "initial_load"


@dataclass(slots=True)
class ArtistClusterAssignment:
    """An artist's cluster, either proposed or confirmed."""

    artist_id: int
    cluster_id: int
    confirmed: bool = False


@dataclass(slots=True)
class EraBand:
    """One band of an artist's discography; albums point at it via era_band_id.

    The label is free text: early/middle/late from the sorting engine, or
    whatever an initial load supplied (e.g. "1990s").
    """

    id: int
    artist_id: int
    label: str
    position: int
    source: EraBandSource = EraBandSource.ALGORITHM
