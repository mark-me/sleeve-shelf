"""Connections: how the artists of the collection are tied together, as a network around one
artist or over the whole collection. Visitors may look too."""

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

from sleeve_shelf.library.artists import picture_thumb
from sleeve_shelf.domain import Artist, ArtistEnrichment, sort_name
from sleeve_shelf.insights.connections import network, set_unrelated, ties_of, unrelated_pairs
from sleeve_shelf.insights.network import way
from sleeve_shelf.insights.ties import Tie
from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.sorting.families import names_inside
from sleeve_shelf.web.context import get_store
from sleeve_shelf.web.covers import local_cover

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
    to_id = request.args.get("to", type=int)
    if to_id is not None and (artist_id is None or to_id not in points):
        abort(404)
    text = request.args.get("q", "").strip()
    found = _matching(shown, text) if artist_id is None and text else []
    # The way to another artist: first the artists matching what was typed, then the way.
    way_text = request.args.get("way", "").strip()
    way_found = _matching(shown, way_text, leave_out=artist_id) if artist_id is not None and way_text and to_id is None else []
    clusters = dict(shown.clusters)
    switched, ties_param = _switched(artist_id is not None)
    the_way = way(shown, artist_id, to_id, switched) if to_id is not None else None
    return render_template(
        "connections/index.html",
        ties=list(Tie),
        # The kinds of tie switched on, and how links carry them (None: the defaults).
        switched=switched,
        ties_param=ties_param,
        artist=points.get(artist_id),
        cluster=clusters.get(points[artist_id].cluster_id) if artist_id is not None else None,
        steps=2 if request.args.get("steps") == "2" else 1,
        # A label ties an artist to many: they are listed only when asked for.
        around=ties_of(store, shown, artist_id, frozenset() if Tie.LABEL in switched else frozenset({Tie.LABEL}))
        if artist_id is not None
        else [],
        # Where each album stands, to take it from the shelf.
        places={row.album_id: row for row in BrowseQueries(store).everything()} if artist_id is not None else {},
        clusters=clusters,
        search_text=text,
        found=found,
        to=points.get(to_id),
        the_way=the_way,
        way_text=way_text,
        way_found=way_found,
        tied={point for link in shown.links for point in (link.one, link.other)},
        # Those the owner said are not related to this artist, to take that back.
        unrelated=[
            points[one if other == artist_id else other]
            for one, other in sorted(unrelated_pairs(store))
            if artist_id in (one, other) and one in points and other in points
        ],
    )


@blueprint.post("/unrelated")
def unrelated():
    """A name inside another does not make these two related, or does after all (undo); back to
    the artist it was said on. Nothing but the name's tie goes: what Discogs lists stays."""
    store = get_store()
    artist_id = request.form.get("artist", type=int)
    other_id = request.form.get("other", type=int)
    known = {artist.id for artist in store.load(Artist)}
    if artist_id not in known or other_id not in known or artist_id == other_id:
        abort(400)
    set_unrelated(store, artist_id, other_id, "undo" not in request.form)
    return redirect(url_for("connections.index", artist=artist_id, ties=request.form.get("ties") or None))


def _matching(shown, text: str, leave_out: int | None = None) -> list:
    """The artists whose name holds every word typed, by name."""
    words = sort_name(text).split()
    return sorted(
        (
            point
            for point in shown.points
            if point.artist_id != leave_out and all(word in sort_name(point.name) for word in words)
        ),
        key=lambda point: sort_name(point.name),
    )[:FOUND_LIMIT]


def _switched(around_one: bool) -> tuple[set[Tie], str | None]:
    """The kinds of tie switched on: as the link says once the user switched one, or else the
    defaults — everything but Same label, which ties an artist to many, and Same song only
    around one artist, as over the whole collection it ties almost every jazz artist to every
    other."""
    given = request.args.get("ties")
    if given is None:
        return {tie for tie in Tie if tie is not Tie.LABEL and (around_one or tie is not Tie.SONGS)}, None
    switched = {tie for tie in Tie if tie.value in given.split(",")}
    return switched, ",".join(tie.value for tie in Tie if tie in switched)


@blueprint.get("/network.json")
def data():
    """The whole network, for the screen's script to draw: compact lists rather than objects."""
    store = get_store()
    shown = network(store)
    pictures = _pictures(store)
    return jsonify(
        {
            "clusters": [[cluster_id, name] for cluster_id, name in shown.clusters],
            "artists": [
                [p.artist_id, p.name, p.albums, p.cluster_id, *pictures.get(p.artist_id, (None, False))]
                for p in shown.points
            ],
            "links": [
                [
                    link.one,
                    link.other,
                    list(link.ties),
                    list(link.songs),
                    [[entry.name, ", ".join(entry.roles), entry.album_title] for entry in link.on_record],
                    list(link.labels),
                ]
                for link in shown.links
            ],
        }
    )


def _pictures(store) -> dict[int, tuple[str, bool]]:
    """The small picture of each artist that has one kept in the data directory, as (address,
    borrowed): the owner's own, else the one a sync stored. One still at Discogs is left out —
    the network draws on a canvas, which takes images from the app itself only, and it works
    offline too. A joint billing has no page on Discogs, so no picture of its own: it borrows
    that of the first artist it names who has one."""
    if not store.exists(Artist):
        return {}
    thumbs = {
        record.discogs_artist_id: record.thumb_url
        for record in store.load(ArtistEnrichment)
        if record.thumb_url
    }
    artists = store.load(Artist)
    found = {}
    for artist in artists:
        if artist.picture_file:
            found[artist.id] = (url_for("artists.picture", name=picture_thumb(store, artist)), False)
        elif artist.discogs_artist_id in thumbs:
            local = local_cover(thumbs[artist.discogs_artist_id])
            if local != thumbs[artist.discogs_artist_id]:
                found[artist.id] = (local, False)
    for artist_id, named in names_inside(artists, unrelated_pairs(store)).items():
        if artist_id not in found:
            lender = next((other for other in named if other in found and not found[other][1]), None)
            if lender is not None:
                found[artist_id] = (found[lender][0], True)
    return found
