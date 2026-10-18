"""Storage structure: managing the cabinets and their shelves."""

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_babel import gettext as _

from sleeve_shelf.domain import (
    Cabinet,
    Shelf,
    ShelfLayer,
    ShelfType,
    find_by_id,
    in_order,
)
from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.storage import (
    StillInUse,
    remove_cabinet,
    remove_shelf,
    save_cabinet,
    save_shelf,
)
from sleeve_shelf.storage import (
    move_cabinet as move_cabinet_in_order,
)
from sleeve_shelf.storage import (
    move_shelf as move_shelf_in_order,
)
from sleeve_shelf.web.context import get_store, has_collection, parse_number, shelf_fill
from sleeve_shelf.web.language import editable

blueprint = Blueprint("storage", __name__, url_prefix="/storage")


@blueprint.get("/")
def index():
    store = get_store()
    fill = BrowseQueries(store).shelf_fill() if has_collection() else {}
    shelves = store.load(Shelf)
    cabinets = [
        {
            "cabinet": cabinet,
            "shelves": [
                {"shelf": shelf, **shelf_fill(fill, shelf.id)}
                for shelf in in_order(shelves)
                if shelf.cabinet_id == cabinet.id
            ],
        }
        for cabinet in in_order(store.load(Cabinet))
    ]
    # A column nobody filled in for any shelf only shows dashes: it is left out.
    columns = {
        "type": any(shelf.type for shelf in shelves),
        "layer": any(shelf.layer for shelf in shelves),
        "reachability": any(shelf.reachability_score is not None for shelf in shelves),
        "showcase": any(shelf.is_showcase for shelf in shelves),
    }
    return render_template(
        "storage/index.html", cabinets=cabinets, columns=columns, error=request.args.get("error")
    )


@blueprint.route("/cabinets/new", methods=["GET", "POST"])
def new_cabinet():
    return _cabinet_form(None)


@blueprint.route("/cabinets/<int:cabinet_id>", methods=["GET", "POST"])
def edit_cabinet(cabinet_id: int):
    return _cabinet_form(cabinet_id)


def _cabinet_form(cabinet_id: int | None):
    store = get_store()
    cabinet = _find(store.load(Cabinet), cabinet_id) if cabinet_id is not None else None
    values = (
        {"name": cabinet.name, "location": cabinet.location or "", "outside_sorting": cabinet.outside_sorting}
        if cabinet
        else {}
    )
    errors: list[str] = []
    if request.method == "POST":
        values = {key: request.form.get(key, "").strip() for key in ("name", "location")}
        values["outside_sorting"] = "outside_sorting" in request.form
        if not values["name"]:
            errors.append(_("Give the cabinet a name."))
        if not errors:
            save_cabinet(store, cabinet_id, values["name"], values["location"], values["outside_sorting"])
            return redirect(url_for("storage.index"))
    status = 400 if errors else 200
    return render_template(
        "storage/cabinet_form.html", cabinet=cabinet, values=values, errors=errors
    ), status


@blueprint.post("/cabinets/<int:cabinet_id>/delete")
def delete_cabinet(cabinet_id: int):
    store = get_store()
    cabinet = _find(store.load(Cabinet), cabinet_id)
    try:
        remove_cabinet(store, cabinet_id)
    except StillInUse:
        return _refuse(_("Remove the shelves of “%(name)s” before removing the cabinet.", name=cabinet.name))
    return redirect(url_for("storage.index"))


@blueprint.post("/cabinets/<int:cabinet_id>/move")
def move_cabinet(cabinet_id: int):
    store = get_store()
    _find(store.load(Cabinet), cabinet_id)
    move_cabinet_in_order(store, cabinet_id, _step())
    return redirect(url_for("storage.index") + f"#cabinet-{cabinet_id}")


@blueprint.post("/shelves/<int:shelf_id>/move")
def move_shelf(shelf_id: int):
    store = get_store()
    _find(store.load(Shelf), shelf_id)
    cabinet_id = move_shelf_in_order(store, shelf_id, _step())
    return redirect(url_for("storage.index") + f"#cabinet-{cabinet_id}")


def _step() -> int:
    return -1 if request.form.get("direction") == "up" else 1


@blueprint.route("/cabinets/<int:cabinet_id>/shelves/new", methods=["GET", "POST"])
def new_shelf(cabinet_id: int):
    cabinet = _find(get_store().load(Cabinet), cabinet_id)
    return _shelf_form(cabinet, None)


@blueprint.route("/shelves/<int:shelf_id>", methods=["GET", "POST"])
def edit_shelf(shelf_id: int):
    store = get_store()
    shelf = _find(store.load(Shelf), shelf_id)
    return _shelf_form(_find(store.load(Cabinet), shelf.cabinet_id), shelf_id)


def _shelf_form(cabinet: Cabinet, shelf_id: int | None):
    store = get_store()
    shelf = _find(store.load(Shelf), shelf_id) if shelf_id is not None else None
    if shelf:
        values = {
            "name": shelf.name,
            "width_cm": "" if shelf.width_cm is None else editable(shelf.width_cm),
            "type": shelf.type or "",
            "layer": shelf.layer or "",
            "reachability_score": "" if shelf.reachability_score is None else str(shelf.reachability_score),
            "is_showcase": shelf.is_showcase,
            "width_measured": shelf.width_measured,
        }
    else:
        # A shelf added by hand is usually measured on the spot.
        values = {"is_showcase": False, "width_measured": True}
    errors: list[str] = []
    if request.method == "POST":
        form = request.form
        values = {
            key: form.get(key, "").strip()
            for key in ("name", "width_cm", "type", "layer", "reachability_score")
        }
        values["is_showcase"] = "is_showcase" in form
        values["width_measured"] = "width_measured" in form
        width = _positive_number(values["width_cm"])
        reachability = _positive_number(values["reachability_score"])
        if not values["name"]:
            errors.append(_("Give the shelf a name."))
        if values["width_cm"] and width is None:
            errors.append(_("The width has to be a number of centimetres above zero."))
        if values["reachability_score"] and (reachability is None or reachability != int(reachability)):
            errors.append(_("Reachability has to be a whole number, 1 being the easiest to reach."))
        if values["is_showcase"] and values["type"] != ShelfType.TOP_LOADER:
            errors.append(_("Only a top-loader shelf can be a showcase."))
        if not errors:
            save_shelf(
                store,
                cabinet.id,
                shelf_id,
                values["name"],
                width_cm=width,
                type=ShelfType(values["type"]) if values["type"] else None,
                layer=ShelfLayer(values["layer"]) if values["layer"] else None,
                reachability_score=int(reachability) if reachability else None,
                is_showcase=values["is_showcase"],
                width_measured=values["width_measured"],
            )
            return redirect(url_for("storage.index"))
    status = 400 if errors else 200
    return render_template(
        "storage/shelf_form.html", cabinet=cabinet, shelf=shelf, values=values, errors=errors
    ), status


@blueprint.post("/shelves/<int:shelf_id>/delete")
def delete_shelf(shelf_id: int):
    store = get_store()
    shelf = _find(store.load(Shelf), shelf_id)
    try:
        remove_shelf(store, shelf_id)
    except StillInUse:
        return _refuse(_("Shelf “%(name)s” still holds albums; move them before removing it.", name=shelf.name))
    return redirect(url_for("storage.index"))


def _find(items: list, item_id: int | None):
    item = find_by_id(items, item_id)
    if item is None:
        abort(404)
    return item


def _positive_number(text: str) -> float | None:
    """A number above zero, accepting a decimal comma; None when it isn't one."""
    number = parse_number(text)
    return number if number is not None and number > 0 else None


def _refuse(message: str):
    return redirect(url_for("storage.index", error=message))
