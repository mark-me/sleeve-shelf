"""Location rules: fixed exceptions that bind something to a cabinet."""

from flask import Blueprint, redirect, render_template, request, url_for
from flask_babel import gettext as _

from sleeve_shelf.domain import (
    Album,
    AliasGroup,
    Artist,
    Cabinet,
    Cluster,
    LocationRule,
    LocationRuleTarget,
    in_order,
)
from sleeve_shelf.web.context import get_store

blueprint = Blueprint("rules", __name__, url_prefix="/rules")


def _targets(store) -> dict[LocationRuleTarget, dict[int, str]]:
    """Everything a rule can point at, by kind: id to the name it is shown and chosen by."""
    artists = {artist.id: artist.name for artist in store.load(Artist)}
    return {
        LocationRuleTarget.CLUSTER: {c.id: c.name for c in store.load(Cluster)},
        LocationRuleTarget.ALIAS_GROUP: {g.id: g.label for g in store.load(AliasGroup)},
        LocationRuleTarget.ARTIST: artists,
        LocationRuleTarget.ALBUM: {
            album.id: f"{artists.get(album.artist_id, '')} — {album.title}"
            for album in store.load(Album)
        },
    }


@blueprint.get("/")
def index():
    store = get_store()
    targets = _targets(store)
    cabinets = in_order(store.load(Cabinet))
    cabinet_names = {cabinet.id: cabinet.name for cabinet in cabinets}
    rules = [
        {
            "rule": rule,
            "target": targets[rule.target_type].get(rule.target_id),
            "cabinet": cabinet_names.get(rule.cabinet_id),
        }
        for rule in store.load(LocationRule)
    ]
    return render_template(
        "rules/index.html",
        rules=rules,
        cabinets=cabinets,
        options={
            kind.value: sorted(set(names.values()), key=str.casefold)
            for kind, names in targets.items()
        },
        error=request.args.get("error"),
    )


@blueprint.post("/new")
def create():
    store = get_store()
    try:
        kind = LocationRuleTarget(request.form.get("target_type", ""))
    except ValueError:
        return _back(_("Choose what the rule is for."))
    name = request.form.get("target", "").strip().casefold()
    target_id = next(
        (i for i, label in _targets(store)[kind].items() if label.casefold() == name), None
    )
    cabinet_id = request.form.get("cabinet_id", type=int)
    if target_id is None:
        return _back(_("Choose a name from the list."))
    if all(cabinet.id != cabinet_id for cabinet in store.load(Cabinet)):
        return _back(_("Choose a cabinet."))
    rules = [
        rule
        for rule in store.load(LocationRule)
        # One rule per target: a new one replaces the old.
        if (rule.target_type, rule.target_id) != (kind, target_id)
    ]
    rules.append(
        LocationRule(
            max((rule.id for rule in rules), default=0) + 1,
            kind,
            target_id,
            cabinet_id,
            request.form.get("note", "").strip(),
        )
    )
    store.save(LocationRule, rules)
    return _back()


@blueprint.post("/<int:rule_id>/delete")
def delete(rule_id: int):
    store = get_store()
    store.save(LocationRule, [rule for rule in store.load(LocationRule) if rule.id != rule_id])
    return _back()


def _back(error: str | None = None):
    return redirect(url_for("rules.index", error=error))
