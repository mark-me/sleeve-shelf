"""Connections: how the artists of the collection are tied together, as a network around one
artist or over the whole collection. Visitors may look too."""

from flask import Blueprint, abort, jsonify, render_template, request

from sleeve_shelf.network import Tie, network
from sleeve_shelf.sorting.families import sort_name
from sleeve_shelf.web.context import get_store

blueprint = Blueprint("connections", __name__, url_prefix="/connections")

# How many artists a search on the screen lists.
FOUND_LIMIT = 20


@blueprint.get("/")
def index():
    store = get_store()
    shown = network(store)
    points = {point.artist_id: point for point in shown.points}
    artist_id = request.args.get("artist", type=int)
    if artist_id is not None and artist_id not in points:
        abort(404)
    text = request.args.get("q", "").strip()
    found = []
    if artist_id is None and text:
        words = sort_name(text).split()
        found = sorted(
            (point for point in shown.points if all(word in sort_name(point.name) for word in words)),
            key=lambda point: sort_name(point.name),
        )[:FOUND_LIMIT]
    clusters = dict(shown.clusters)
    return render_template(
        "connections/index.html",
        ties=list(Tie),
        artist=points.get(artist_id),
        cluster=clusters.get(points[artist_id].cluster_id) if artist_id is not None else None,
        steps=2 if request.args.get("steps") == "2" else 1,
        around=shown.around(artist_id) if artist_id is not None else [],
        clusters=clusters,
        search_text=text,
        found=found,
        tied={point for link in shown.links for point in (link.one, link.other)},
    )


@blueprint.get("/network.json")
def data():
    """The whole network, for the screen's script to draw: compact lists rather than objects."""
    shown = network(get_store())
    return jsonify(
        {
            "clusters": [[cluster_id, name] for cluster_id, name in shown.clusters],
            "artists": [[p.artist_id, p.name, p.albums, p.cluster_id] for p in shown.points],
            "links": [[link.one, link.other, list(link.ties), list(link.songs)] for link in shown.links],
        }
    )
