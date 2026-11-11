"""All cabinets at a glance: every shelf as a strip of its clusters, the shelves or a proposal.

So the whole can be seen at once while albums, artists or clusters are moved: which shelves fill
up, which empty, and where each cluster runs.
"""

from sleeve_shelf.domain import Album, Cabinet, Cluster, Placement, Shelf, WidthConstants, in_order
from sleeve_shelf.persistence import BrowseQueries, JsonStore


def at_a_glance(store: JsonStore, constants: WidthConstants, layout: type[Placement] = Placement) -> dict:
    """Every cabinet with its shelves, each shelf as the runs of one cluster after another.

    Args:
        store: The store of the collection.
        constants: The width figures, for an album without a width of its own.
        layout: The shelves (Placement) or the proposal (ProposedPlacement).

    Returns:
        What the overview's template uses: the cabinets, the clusters in their order with their
        place in it (which decides their colour), and the widest shelf, to draw all to one scale.
    """
    widths = {album.id: album.width_cm or constants.base_per_disc for album in store.load(Album)}
    clusters = in_order(store.load(Cluster))
    order = {cluster.name: index for index, cluster in enumerate(clusters)}
    on_shelf = BrowseQueries(store, layout).by_shelf()
    shelves = store.load(Shelf)
    cabinets = []
    for cabinet in in_order(store.load(Cabinet)):
        rows = []
        for shelf in in_order([s for s in shelves if s.cabinet_id == cabinet.id]):
            runs: list[dict] = []
            for album in on_shelf.get(shelf.id, []):
                cm = widths.get(album.album_id, constants.base_per_disc)
                if runs and runs[-1]["cluster"] == album.cluster:
                    runs[-1]["cm"] += cm
                    runs[-1]["albums"] += 1
                else:
                    runs.append({"cluster": album.cluster, "index": order.get(album.cluster), "cm": cm, "albums": 1})
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
            cabinets.append({"cabinet": cabinet, "shelves": rows})
    widest = max(
        (max(row["shelf"].width_cm or 0.0, row["filled_cm"]) for entry in cabinets for row in entry["shelves"]),
        default=0.0,
    )
    return {
        "cabinets": cabinets,
        "clusters": [{"name": cluster.name, "index": index} for index, cluster in enumerate(clusters)],
        "widest_cm": widest or 1.0,
    }
