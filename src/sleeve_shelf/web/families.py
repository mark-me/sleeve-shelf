"""Alias groups: the artist families that stand together on the shelf."""

from collections import Counter

from flask import Blueprint, redirect, render_template, request, url_for
from flask_babel import gettext as _

from sleeve_shelf import alias_groups
from sleeve_shelf.domain import Album, AliasGroup, Artist, ArtistClusterAssignment, Cluster
from sleeve_shelf.web.context import get_store

blueprint = Blueprint("families", __name__, url_prefix="/families")


@blueprint.get("/")
def index():
    store = get_store()
    artists = store.load(Artist)
    by_id = {artist.id: artist for artist in artists}
    album_counts = Counter(album.artist_id for album in store.load(Album))
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

    suggestions = [
        {
            "anchor": describe(suggestion.anchor_id),
            "members": [describe(member_id) for member_id in suggestion.member_ids],
        }
        for suggestion in alias_groups.family_suggestions(store)
    ]
    families = [
        {
            "group": group,
            "members": sorted(
                (describe(a.id) for a in artists if a.alias_group_id == group.id),
                key=lambda member: member["name"].casefold(),
            ),
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
