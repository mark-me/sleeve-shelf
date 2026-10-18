"""Alias groups: the artist families that stand together on the shelf."""

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_babel import gettext as _

from sleeve_shelf import alias_groups
from sleeve_shelf.artists import albums_per_artist
from sleeve_shelf.config import load_settings
from sleeve_shelf.domain import (
    AliasGroup,
    Artist,
    ArtistClusterAssignment,
    Cluster,
    find_by_id,
)
from sleeve_shelf.placing import ShelvesChanged, family_albums_on_shelves, place_family
from sleeve_shelf.web.context import get_store, has_collection
from sleeve_shelf.web.places import placed_args, placed_notice, run_targets, run_width

blueprint = Blueprint("families", __name__, url_prefix="/families")


@blueprint.get("/")
def index():
    store = get_store()
    artists = store.load(Artist)
    by_id = {artist.id: artist for artist in artists}
    album_counts = albums_per_artist(store)
    cluster_names = {cluster.id: cluster.name for cluster in store.load(Cluster)}
    cluster_of = {
        assignment.artist_id: cluster_names.get(assignment.cluster_id)
        for assignment in store.load(ArtistClusterAssignment)
    }

    def describe(artist_id: int) -> dict:
        return {
            "id": artist_id,
            "name": by_id[artist_id].name,
            "albums": album_counts[artist_id],
            "cluster": cluster_of.get(artist_id),
        }

    labels = {group.id: group.label for group in store.load(AliasGroup)}
    suggestions = [
        {
            "anchor": describe(suggestion.anchor_id),
            "members": [describe(member_id) for member_id in suggestion.member_ids],
            # The family the members would be added to, when the suggestion is not a new one.
            "family": labels.get(suggestion.group_id),
            "source": suggestion.source,
        }
        for suggestion in alias_groups.family_suggestions(store)
    ]
    # What each family would take on the shelves, to move it at once (see placing.place_family).
    on_shelves = family_albums_on_shelves(store) if has_collection() else {}
    families = [
        {
            "group": group,
            "members": sorted(
                (describe(a.id) for a in artists if a.alias_group_id == group.id),
                key=lambda member: member["name"].casefold(),
            ),
            "on_shelves": len(on_shelves.get(group.id, [])),
            "on_shelves_cm": run_width(store, on_shelves.get(group.id, [])),
        }
        for group in sorted(store.load(AliasGroup), key=lambda group: group.label.casefold())
    ]
    return render_template(
        "families/index.html",
        suggestions=suggestions,
        families=families,
        free_artists=sorted(
            (a.name for a in artists if a.alias_group_id is None), key=str.casefold
        ),
        error=request.args.get("error"),
        targets=run_targets(store),
        placed=placed_notice(store, request.args),
        placed_family=request.args.get("family", type=int),
    )


@blueprint.post("/<int:group_id>/place")
def place(group_id: int):
    """Stand the whole family from a chosen shelf on (see placing.place_family)."""
    store = get_store()
    if find_by_id(store.load(AliasGroup), group_id) is None:
        abort(404)
    shelf_id = request.form.get("shelf_id", type=int)
    try:
        result = place_family(store, group_id, shelf_id, load_settings(store.data_dir).width_constants)
    except ShelvesChanged:
        abort(400)
    return redirect(
        url_for("families.index", family=group_id, **placed_args(result, shelf_id)) + f"#family-{group_id}"
    )


@blueprint.post("/suggestions/<int:anchor_id>/accept")
def accept(anchor_id: int):
    member_ids = request.form.getlist("member", type=int)
    alias_groups.accept_suggestion(get_store(), anchor_id, member_ids)
    return _back("suggestions")


@blueprint.post("/suggestions/accept-all")
def accept_all():
    store = get_store()
    for suggestion in alias_groups.family_suggestions(store):
        alias_groups.accept_suggestion(store, suggestion.anchor_id, list(suggestion.member_ids))
    return _back("families")


@blueprint.post("/suggestions/<int:anchor_id>/dismiss")
def dismiss(anchor_id: int):
    alias_groups.dismiss_suggestion(get_store(), anchor_id)
    return _back("suggestions")


@blueprint.post("/new")
def create():
    label = request.form.get("label", "").strip()
    if not label:
        return _back("families", _("Give the family a name."))
    group = alias_groups.create_family(get_store(), label)
    return redirect(url_for("families.index") + f"#family-{group.id}")


@blueprint.post("/<int:group_id>/rename")
def rename(group_id: int):
    label = request.form.get("label", "").strip()
    if not label:
        return _back(f"family-{group_id}", _("Give the family a name."))
    alias_groups.rename_family(get_store(), group_id, label)
    return _back(f"family-{group_id}")


@blueprint.post("/<int:group_id>/delete")
def delete(group_id: int):
    alias_groups.delete_family(get_store(), group_id)
    return _back("families")


@blueprint.post("/<int:group_id>/members")
def add_member(group_id: int):
    store = get_store()
    name = request.form.get("artist", "").strip().casefold()
    artist = next((a for a in store.load(Artist) if a.name.casefold() == name), None)
    if artist is None:
        return _back(f"family-{group_id}", _("Choose an artist from the list."))
    alias_groups.set_family(store, artist.id, group_id)
    return _back(f"family-{group_id}")


@blueprint.post("/members/<int:artist_id>/remove")
def remove_member(artist_id: int):
    alias_groups.set_family(get_store(), artist_id, None)
    return _back("families")


def _back(anchor: str, error: str | None = None):
    return redirect(url_for("families.index", error=error) + f"#{anchor}")
