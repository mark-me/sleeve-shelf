"""Clusters: their names, their order, merging them, and the styles that point at them."""

from collections import Counter

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_babel import gettext as _

from sleeve_shelf.clusters import (
    album_counts,
    clusters_in_order,
    delete_empty_cluster,
    merge_clusters,
    move_cluster,
    point_style,
    rename_cluster,
)
from sleeve_shelf.config import load_settings
from sleeve_shelf.domain import (
    ArtistClusterAssignment,
    Cluster,
    Style,
    find_by_id,
)
from sleeve_shelf.placing import (
    ShelvesChanged,
    cluster_albums_on_shelves,
    place_cluster,
)
from sleeve_shelf.web.context import get_store
from sleeve_shelf.web.places import placed_args, placed_notice, run_targets, run_width

blueprint = Blueprint("clusters", __name__, url_prefix="/clusters")


@blueprint.get("/")
def index():
    store = get_store()
    albums = album_counts(store)
    artists = Counter(a.cluster_id for a in store.load(ArtistClusterAssignment))
    styles: dict[int, list[Style]] = {}
    for style in sorted(store.load(Style), key=lambda style: style.name.casefold()):
        styles.setdefault(style.cluster_id, []).append(style)
    rows = [
        {
            "cluster": cluster,
            "artists": artists[cluster.id],
            "albums": albums[cluster.id],
            "styles": styles.get(cluster.id, []),
        }
        for cluster in clusters_in_order(store.load(Cluster))
    ]
    return render_template("clusters/index.html", rows=rows, error=request.args.get("error"))


@blueprint.route("/<int:cluster_id>", methods=["GET", "POST"])
def edit(cluster_id: int):
    store = get_store()
    clusters = clusters_in_order(store.load(Cluster))
    cluster = find_by_id(clusters, cluster_id)
    if cluster is None:
        abort(404)
    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            rename_cluster(store, cluster_id, name)
            return redirect(url_for("clusters.edit", cluster_id=cluster_id))
        error = _("Give the cluster a name.")
    return (
        render_template(
            "clusters/edit.html",
            cluster=cluster,
            clusters=clusters,
            styles=sorted(
                (s for s in store.load(Style) if s.cluster_id == cluster_id),
                key=lambda style: style.name.casefold(),
            ),
            artist_count=sum(
                1 for a in store.load(ArtistClusterAssignment) if a.cluster_id == cluster_id
            ),
            album_count=album_counts(store)[cluster_id],
            error=error,
            **_placing(store, cluster_id),
        ),
        400 if error else 200,
    )


def _placing(store, cluster_id: int) -> dict:
    """What moving the cluster to a shelf would take, and where it can go; and what the last
    move did, to say so."""
    on_shelves = cluster_albums_on_shelves(store, cluster_id)
    return {
        "on_shelves": len(on_shelves),
        "on_shelves_cm": run_width(store, on_shelves),
        "targets": run_targets(store),
        "placed": placed_notice(store, request.args),
    }


@blueprint.post("/<int:cluster_id>/place")
def place(cluster_id: int):
    """Stand the whole cluster from a chosen shelf on (see placing.place_cluster)."""
    store = get_store()
    if find_by_id(store.load(Cluster), cluster_id) is None:
        abort(404)
    shelf_id = request.form.get("shelf_id", type=int)
    try:
        result = place_cluster(store, cluster_id, shelf_id, load_settings(store.data_dir).width_constants)
    except ShelvesChanged:
        abort(400)
    return redirect(url_for("clusters.edit", cluster_id=cluster_id, **placed_args(result, shelf_id)) + "#place")


@blueprint.post("/<int:cluster_id>/move")
def move(cluster_id: int):
    move_cluster(get_store(), cluster_id, -1 if request.form.get("direction") == "up" else 1)
    return redirect(url_for("clusters.index") + f"#cluster-{cluster_id}")


@blueprint.post("/merge")
def merge():
    cluster_ids = request.form.getlist("cluster", type=int)
    if len(cluster_ids) < 2:
        return redirect(url_for("clusters.index", error=_("Tick at least two clusters to merge.")))
    survivor = merge_clusters(get_store(), cluster_ids, request.form.get("name", "").strip())
    return redirect(url_for("clusters.index") + f"#cluster-{survivor}")


@blueprint.post("/<int:cluster_id>/delete")
def delete(cluster_id: int):
    if not delete_empty_cluster(get_store(), cluster_id):
        return redirect(
            url_for("clusters.index", error=_("Only a cluster without artists, styles and rules can be removed."))
        )
    return redirect(url_for("clusters.index"))


@blueprint.post("/styles/<int:style_id>")
def move_style(style_id: int):
    point_style(get_store(), style_id, request.form.get("cluster_id", type=int))
    return redirect(request.form.get("next") or url_for("clusters.index"))
