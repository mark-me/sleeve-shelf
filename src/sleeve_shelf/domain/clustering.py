"""Sorting/clustering entities: dominant clusters, era bands, and the cluster ordering."""

from dataclasses import dataclass
from enum import StrEnum


class EraBandSource(StrEnum):
    ALGORITHM = "algorithm"
    INITIAL_LOAD = "initial_load"


@dataclass(slots=True)
class ArtistClusterAssignment:
    """An artist's dominant cluster, either proposed or confirmed.

    A cluster_id of None means the artist is its own standalone cluster.
    """

    artist_id: int
    cluster_id: int | None
    confirmed: bool = False

    @property
    def is_standalone(self) -> bool:
        """Whether the artist forms its own cluster, not tied to any style."""
        return self.cluster_id is None


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


@dataclass(frozen=True, slots=True)
class ClusterOrder:
    """The computed co-occurrence ordering of clusters; recomputed, not persisted."""

    cluster_ids: tuple[int, ...]
