"""Application services for curating the clusters: names, order, merging, and styles."""

from collections import Counter

from sleeve_shelf.domain import (
    Album,
    ArtistClusterAssignment,
    Cluster,
    LocationRule,
    LocationRuleTarget,
    Style,
    move,
)
from sleeve_shelf.persistence import JsonStore


def clusters_in_order(clusters: list[Cluster]) -> list[Cluster]:
    return sorted(
        clusters, key=lambda c: (c.position if c.position is not None else 10**6, c.id)
    )


def rename_cluster(store: JsonStore, cluster_id: int, name: str) -> None:
    clusters = store.load(Cluster)
    for cluster in clusters:
        if cluster.id == cluster_id:
            cluster.name = name
    store.save(Cluster, clusters)


def move_cluster(store: JsonStore, cluster_id: int, step: int) -> None:
    """Move a cluster one place earlier (-1) or later (+1) in the sequence of clusters."""
    clusters = store.load(Cluster)
    if any(cluster.id == cluster_id for cluster in clusters):
        move(clusters, cluster_id, step)
        store.save(Cluster, clusters)


def album_counts(store: JsonStore) -> Counter[int]:
    """How many albums each cluster holds, going by the cluster of each album's artist."""
    cluster_of = {a.artist_id: a.cluster_id for a in store.load(ArtistClusterAssignment)}
    return Counter(
        cluster_of[album.artist_id]
        for album in store.load(Album)
        if cluster_of.get(album.artist_id) is not None
    )


def merge_clusters(store: JsonStore, cluster_ids: list[int], name: str = "") -> int | None:
    """Merge clusters into the one holding the most albums; returns the surviving cluster's id.

    Artists, styles and location rules of the others are repointed to it. The
    survivor keeps its place in the sequence, and takes the given name if any.
    """
    clusters = store.load(Cluster)
    chosen = [cluster for cluster in clusters if cluster.id in cluster_ids]
    if len(chosen) < 2:
        return None
    counts = album_counts(store)
    survivor = max(chosen, key=lambda cluster: (counts[cluster.id], -cluster.id))
    gone = {cluster.id for cluster in chosen} - {survivor.id}
    if name:
        survivor.name = name

    assignments = store.load(ArtistClusterAssignment)
    for assignment in assignments:
        if assignment.cluster_id in gone:
            assignment.cluster_id = survivor.id
    styles = store.load(Style)
    for style in styles:
        if style.cluster_id in gone:
            style.cluster_id = survivor.id
    rules = store.load(LocationRule)
    for rule in rules:
        if rule.target_type is LocationRuleTarget.CLUSTER and rule.target_id in gone:
            rule.target_id = survivor.id
    # Two merged clusters may each have had a rule; the survivor keeps its own, or the first.
    seen: set[tuple] = set()
    kept_rules = []
    for rule in sorted(rules, key=lambda rule: (rule.target_id != survivor.id, rule.id)):
        key = (rule.target_type, rule.target_id)
        if key not in seen:
            seen.add(key)
            kept_rules.append(rule)

    remaining = clusters_in_order([cluster for cluster in clusters if cluster.id not in gone])
    for position, cluster in enumerate(remaining):
        cluster.position = position
    store.save(ArtistClusterAssignment, assignments)
    store.save(Style, styles)
    store.save(LocationRule, sorted(kept_rules, key=lambda rule: rule.id))
    store.save(Cluster, remaining)
    return survivor.id


def delete_empty_cluster(store: JsonStore, cluster_id: int) -> bool:
    """Remove a cluster nothing points at any more; returns whether it was removed."""
    in_use = (
        any(a.cluster_id == cluster_id for a in store.load(ArtistClusterAssignment))
        or any(s.cluster_id == cluster_id for s in store.load(Style))
        or any(
            r.target_type is LocationRuleTarget.CLUSTER and r.target_id == cluster_id
            for r in store.load(LocationRule)
        )
    )
    if in_use:
        return False
    remaining = clusters_in_order([c for c in store.load(Cluster) if c.id != cluster_id])
    for position, cluster in enumerate(remaining):
        cluster.position = position
    store.save(Cluster, remaining)
    return True


def point_style(store: JsonStore, style_id: int, cluster_id: int) -> None:
    """Make a Discogs style point at another cluster, for proposing clusters to new artists."""
    styles = store.load(Style)
    if all(cluster.id != cluster_id for cluster in store.load(Cluster)):
        return
    for style in styles:
        if style.id == style_id:
            style.cluster_id = cluster_id
    store.save(Style, styles)
