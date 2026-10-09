"""Settings: the values in config.yaml."""

from flask import Blueprint, current_app, redirect, render_template, request, url_for
from flask_babel import gettext as _

from sleeve_shelf.collection import estimate_widths
from sleeve_shelf.config import load_settings, save_settings
from sleeve_shelf.domain import Album, Placement, UnitType
from sleeve_shelf.proposal import takes_part, usable_shelves
from sleeve_shelf.web.context import get_store, has_collection

blueprint = Blueprint("settings", __name__, url_prefix="/settings")

WIDTH_FIELDS = ("base_width_cm", "surcharge_180_gram_cm", "surcharge_gatefold_cm")


def _number(text: str) -> float | None:
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


@blueprint.route("/", methods=["GET", "POST"])
def index():
    data_dir = current_app.config["DATA_DIR"]
    settings = load_settings(data_dir)
    store = get_store()
    values = {name: f"{getattr(settings, name):g}" for name in WIDTH_FIELDS}
    errors: list[str] = []

    if request.method == "POST":
        values = {name: request.form.get(name, "").strip() for name in WIDTH_FIELDS}
        numbers = {name: _number(text) for name, text in values.items()}
        if numbers["base_width_cm"] is None or numbers["base_width_cm"] <= 0:
            errors.append(_("The base width has to be a number above zero."))
        if any(numbers[name] is None or numbers[name] < 0 for name in WIDTH_FIELDS[1:]):
            errors.append(_("A surcharge has to be a number, zero or more."))
        fill_text = request.form.get("showcase_fill_percent", "").strip()
        if fill_text and not (fill_text.isdigit() and 1 <= int(fill_text) <= 100):
            errors.append(_("The showcase fill has to be a whole percentage from 1 to 100."))
        if not errors:
            if fill_text:
                settings.showcase_fill_percent = int(fill_text)
            for name in WIDTH_FIELDS:
                setattr(settings, name, numbers[name])
            settings.count_bonus_discs_as_vinyl = "count_bonus_discs_as_vinyl" in request.form
            token = request.form.get("discogs_token", "").strip()
            if token:
                settings.discogs_token = token
            save_settings(data_dir, settings)
            if has_collection():
                # The album widths follow the constants; shelf widths are the user's own.
                albums = store.load(Album)
                estimate_widths(albums, settings.width_constants)
                store.save(Album, albums)
            return redirect(url_for("settings.index", saved=1))

    needed = offered = None
    if has_collection():
        placed = {p.unit_id for p in store.load(Placement) if p.unit_type is UnitType.ALBUM}
        needed = sum(
            album.width_cm or settings.base_width_cm
            for album in store.load(Album)
            if takes_part(album, placed)
        )
        offered = sum(shelf.width_cm for shelf in usable_shelves(store)[0])
    token = settings.discogs_token
    return (
        render_template(
            "settings/index.html",
            values=values,
            count_bonus=settings.count_bonus_discs_as_vinyl
            if request.method == "GET"
            else "count_bonus_discs_as_vinyl" in request.form,
            showcase_fill=request.form.get("showcase_fill_percent", settings.showcase_fill_percent),
            masked_token=f"••••{token[-4:]}" if token else None,
            errors=errors,
            saved=request.args.get("saved") and not errors,
            needed=needed,
            offered=offered,
        ),
        400 if errors else 200,
    )
