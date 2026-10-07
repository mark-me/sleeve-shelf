"""Domain layer: plain objects, independent of storage and the web layer."""

from sleeve_shelf.domain.catalog import (
    Album,
    AliasGroup,
    Artist,
    Cluster,
    FormatTokens,
    Style,
    WidthConstants,
)
from sleeve_shelf.domain.clustering import (
    ArtistClusterAssignment,
    ClusterOrder,
    EraBand,
    EraBandSource,
)
from sleeve_shelf.domain.enrichment import MasterEnrichment, ReleaseEnrichment
from sleeve_shelf.domain.placement import (
    Placement,
    PlacementSource,
    ShowcaseFeature,
    UnitType,
)
from sleeve_shelf.domain.storage import (
    Cabinet,
    LocationRule,
    LocationRuleTarget,
    Shelf,
    ShelfLayer,
    ShelfType,
)

__all__ = [
    "Album",
    "AliasGroup",
    "Artist",
    "ArtistClusterAssignment",
    "Cabinet",
    "Cluster",
    "ClusterOrder",
    "EraBand",
    "EraBandSource",
    "FormatTokens",
    "LocationRule",
    "LocationRuleTarget",
    "MasterEnrichment",
    "Placement",
    "PlacementSource",
    "ReleaseEnrichment",
    "Shelf",
    "ShelfLayer",
    "ShelfType",
    "ShowcaseFeature",
    "Style",
    "UnitType",
    "WidthConstants",
]
