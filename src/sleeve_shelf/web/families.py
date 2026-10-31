"""Alias groups: the artist families that stand together on the shelf."""

from flask import Blueprint, redirect, render_template, request, url_for
from flask_babel import gettext as _

from sleeve_shelf.domain import Artist
from sleeve_shelf.library import alias_groups
from sleeve_shelf.web.context import get_store

blueprint = Blueprint("families", __name__, url_prefix="/families")


@blueprint.get("/")
def index():
    return render_template(
        "families/index.html",
        **alias_groups.families_overview(get_store()),
        error=request.args.get("error"),
    )


@blueprint.post("/suggestions/<int:anchor_id>/accept")
def accept(anchor_id: int):
    member_ids = request.form.getlist("member", type=int)
    alias_groups.accept_suggestion(get_store(), anchor_id, member_ids, request.form.get("source"))
    return _back("suggestions")


@blueprint.post("/suggestions/accept-all")
def accept_all():
    store = get_store()
    for suggestion in alias_groups.family_suggestions(store):
        alias_groups.accept_suggestion(
            store, suggestion.anchor_id, list(suggestion.member_ids), suggestion.source
        )
    return _back("families")


@blueprint.post("/suggestions/<int:anchor_id>/dismiss")
def dismiss(anchor_id: int):
    alias_groups.dismiss_suggestion(get_store(), anchor_id, request.form.get("source"))
    return _back("suggestions")


@blueprint.post("/members/<int:artist_id>/with/<int:with_id>")
def put_with(artist_id: int, with_id: int):
    """A joint billing put with another artist it names, rather than where it was suggested."""
    alias_groups.join(get_store(), artist_id, with_id)
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
