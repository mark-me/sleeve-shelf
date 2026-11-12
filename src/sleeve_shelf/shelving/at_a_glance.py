"""All cabinets at a glance: every shelf as a strip of its clusters, the shelves or a proposal.

So the whole can be seen at once while albums, artists or clusters are moved: which shelves fill
up, which empty, and where each cluster runs.
"""

from sleeve_shelf.domain import Album, Cabinet, Cluster, Placement, Shelf, WidthConstants, in_order
from sleeve_shelf.persistence import BrowseQueries, JsonStore
from sleeve_shelf.shelving.proposal import sort_collection


def at_a_glance(store: JsonStore, constants: WidthConstants, layout: type[Placement] = Placement) -> dict:
    """Every cabinet with its shelves, each shelf as the runs of one cluster after another.

    Args:
        store: The store of the collection.
        constants: The width figures, for an album without a width of its own.
        layout: The shelves (Placement) or the proposal (ProposedPlacement).

    Returns:
        What the overview's template uses: the cabinets, each with its widest shelf to draw its
        shelves to one scale, and the clusters in their order with their place in it (which
        decides their colour).
    """
    widths = {album.id: album.width_cm or constants.base_per_disc for album in store.load(Album)}
    clusters = in_order(store.load(Cluster))
    # By id: two clusters may share a name, and are still two colours.
    order = {cluster.id: index for index, cluster in enumerate(clusters)}
    names = {cluster.id: cluster.name for cluster in clusters}
    # The cluster each artist is sorted in, proposed or confirmed, as a proposal stands it; an
    # artist the sorting leaves out keeps the cluster it was recorded in, if any.
    sorted_in = _cluster_of_each_artist(store)
    on_shelf = BrowseQueries(store, layout).by_shelf()
    shelves = store.load(Shelf)
    cabinets = []
    for cabinet in in_order(store.load(Cabinet)):
        rows = []
        for shelf in in_order([s for s in shelves if s.cabinet_id == cabinet.id]):
            runs: list[dict] = []
            for album in on_shelf.get(shelf.id, []):
                cm = widths.get(album.album_id, constants.base_per_disc)
                cluster_id = sorted_in.get(album.artist_id, album.cluster_id)
                if runs and runs[-1]["cluster_id"] == cluster_id:
                    runs[-1]["cm"] += cm
                    runs[-1]["albums"] += 1
                else:
                    runs.append(
                        {
                            "cluster_id": cluster_id,
                            "cluster": names.get(cluster_id),
                            "index": order.get(cluster_id),
                            "cm": cm,
                            "albums": 1,
                        }
                    )
            filled = sum(run["cm"] for run in runs)
            rows.append(
                {
                    "shelf": shelf,
                    "runs": runs,
                    "filled_cm": filled,
                    "over": bool(shelf.width_cm) and filled > shelf.width_cm,
                }
            )
        if rows:
            # Each cabinet to its own scale: its shelves compare, and a long shelf elsewhere does
            # not make every strip too short to read.
            widest = max(max(row["shelf"].width_cm or 0.0, row["filled_cm"]) for row in rows)
            cabinets.append({"cabinet": cabinet, "shelves": rows, "widest_cm": widest or 1.0})
    return {
        "cabinets": cabinets,
        "clusters": [{"id": cluster.id, "name": cluster.name, "index": index} for index, cluster in enumerate(clusters)],
    }


def _cluster_of_each_artist(store: JsonStore) -> dict[int, int]:
    """Per artist the cluster the sorting puts it in, kept until a data file changes (shared)."""

    def work() -> dict[int, int]:
        return {
            artist_id: unit.cluster_id
            for unit in sort_collection(store).units
            if unit.cluster_id is not None
            for artist_id in unit.artist_ids
        }

    return store.remembered("cluster of each artist", work)
