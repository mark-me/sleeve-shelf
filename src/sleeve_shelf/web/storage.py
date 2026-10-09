"""Storage structure: managing the cabinets and their shelves."""

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_babel import gettext as _

from sleeve_shelf.domain import Cabinet, Shelf, ShelfLayer, ShelfType, in_order, move, settle_order
from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.web.context import get_store, has_collection

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
                {"shelf": shelf, "albums": fill.get(shelf.id, (0, 0.0))[0],
                 "filled_cm": fill.get(shelf.id, (0, 0.0))[1]}
                for shelf in in_order(shelves)
                if shelf.cabinet_id == cabinet.id
            ],
        }
        for cabinet in in_order(store.load(Cabinet))
    ]
    return render_template("storage/index.html", cabinets=cabinets, error=request.args.get("error"))


@blueprint.route("/cabinets/new", methods=["GET", "POST"])
def new_cabinet():
    return _cabinet_form(None)


@blueprint.route("/cabinets/<int:cabinet_id>", methods=["GET", "POST"])
def edit_cabinet(cabinet_id: int):
    return _cabinet_form(cabinet_id)


def _cabinet_form(cabinet_id: int | None):
    store = get_store()
    cabinets = store.load(Cabinet)
    cabinet = _find(cabinets, cabinet_id) if cabinet_id is not None else None
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
            if cabinet is None:
                cabinet = Cabinet(store.next_id(Cabinet, cabinets), values["name"])
                cabinets.append(cabinet)
                settle_order(cabinets, [])
            cabinet.name = values["name"]
            cabinet.location = values["location"] or None
            cabinet.outside_sorting = values["outside_sorting"]
            store.save(Cabinet, cabinets)
            return redirect(url_for("storage.index"))
    status = 400 if errors else 200
    return render_template(
        "storage/cabinet_form.html", cabinet=cabinet, values=values, errors=errors
    ), status


@blueprint.post("/cabinets/<int:cabinet_id>/delete")
def delete_cabinet(cabinet_id: int):
    store = get_store()
    cabinets = store.load(Cabinet)
    cabinet = _find(cabinets, cabinet_id)
    if any(shelf.cabinet_id == cabinet_id for shelf in store.load(Shelf)):
        return _refuse(_("Remove the shelves of “%(name)s” before removing the cabinet.", name=cabinet.name))
    cabinets.remove(cabinet)
    store.save(Cabinet, cabinets)
    return redirect(url_for("storage.index"))


@blueprint.post("/cabinets/<int:cabinet_id>/move")
def move_cabinet(cabinet_id: int):
    store = get_store()
    cabinets = store.load(Cabinet)
    _find(cabinets, cabinet_id)
    move(cabinets, cabinet_id, _step())
    store.save(Cabinet, cabinets)
    return redirect(url_for("storage.index") + f"#cabinet-{cabinet_id}")


@blueprint.post("/shelves/<int:shelf_id>/move")
def move_shelf(shelf_id: int):
    store = get_store()
    shelves = store.load(Shelf)
    shelf = _find(shelves, shelf_id)
    move([s for s in shelves if s.cabinet_id == shelf.cabinet_id], shelf_id, _step())
    store.save(Shelf, shelves)
    return redirect(url_for("storage.index") + f"#cabinet-{shelf.cabinet_id}")


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
    shelves = store.load(Shelf)
    shelf = _find(shelves, shelf_id) if shelf_id is not None else None
    if shelf:
        values = {
            "name": shelf.name,
            "width_cm": "" if shelf.width_cm is None else f"{shelf.width_cm:g}",
            "type": shelf.type or "",
            "layer": shelf.layer or "",
            "reachability_score": "" if shelf.reachability_score is None else str(shelf.reachability_score),
            "is_showcase": shelf.is_showcase,
        }
    else:
        values = {"is_showcase": False}
    errors: list[str] = []
    if request.method == "POST":
        form = request.form
        values = {
            key: form.get(key, "").strip()
            for key in ("name", "width_cm", "type", "layer", "reachability_score")
        }
        values["is_showcase"] = "is_showcase" in form
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
            if shelf is None:
                shelf = Shelf(store.next_id(Shelf, shelves), cabinet.id, values["name"])
                shelves.append(shelf)
                settle_order([cabinet], shelves)
            shelf.name = values["name"]
            shelf.width_cm = width
            shelf.type = ShelfType(values["type"]) if values["type"] else None
            shelf.layer = ShelfLayer(values["layer"]) if values["layer"] else None
            shelf.reachability_score = int(reachability) if reachability else None
            shelf.is_showcase = values["is_showcase"]
            store.save(Shelf, shelves)
            return redirect(url_for("storage.index"))
    status = 400 if errors else 200
    return render_template(
        "storage/shelf_form.html", cabinet=cabinet, shelf=shelf, values=values, errors=errors
    ), status


@blueprint.post("/shelves/<int:shelf_id>/delete")
def delete_shelf(shelf_id: int):
    store = get_store()
    shelves = store.load(Shelf)
    shelf = _find(shelves, shelf_id)
    if has_collection() and shelf_id in BrowseQueries(store).shelf_fill():
        return _refuse(_("Shelf “%(name)s” still holds albums; move them before removing it.", name=shelf.name))
    shelves.remove(shelf)
    store.save(Shelf, shelves)
    return redirect(url_for("storage.index"))


def _find(items: list, item_id: int | None):
    item = next((item for item in items if item.id == item_id), None)
    if item is None:
        abort(404)
    return item


def _positive_number(text: str) -> float | None:
    """A number above zero, accepting a decimal comma; None when it isn't one."""
    try:
        number = float(text.replace(",", "."))
    except ValueError:
        return None
    return number if number > 0 else None


def _refuse(message: str):
    return redirect(url_for("storage.index", error=message))
