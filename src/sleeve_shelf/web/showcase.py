"""Showcase: the top-loaders that show a sample of the well-represented artists."""

from flask import Blueprint, current_app, redirect, render_template, request, url_for
from flask_babel import gettext as _

from sleeve_shelf.config import load_settings
from sleeve_shelf.domain import Cabinet, Shelf, in_order
from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.showcase import samples, swap
from sleeve_shelf.web.context import get_store, has_collection

blueprint = Blueprint("showcase", __name__, url_prefix="/showcase")


@blueprint.before_request
def require_collection():
    if not has_collection():
        return redirect(url_for("setup.welcome"))


@blueprint.get("/")
def index():
    store = get_store()
    settings = load_settings(current_app.config["DATA_DIR"])
    fill = BrowseQueries(store).shelf_fill()
    shelves = store.load(Shelf)
    showcases = []
    for cabinet in in_order(store.load(Cabinet)):
        for shelf in in_order([s for s in shelves if s.cabinet_id == cabinet.id]):
            if not shelf.is_showcase:
                continue
            shown = samples(store, shelf.id)
            albums, filled_cm = fill.get(shelf.id, (0, 0.0))
            # A top-loader is flipped through, so only part of its width may be taken.
            room_cm = shelf.width_cm * settings.showcase_fill_percent / 100 if shelf.width_cm else None
            showcases.append(
                {
                    "shelf": shelf,
                    "cabinet": cabinet.name,
                    "albums": albums,
                    "filled_cm": filled_cm,
                    "room_cm": room_cm,
                    "too_full": room_cm is not None and filled_cm > room_cm,
                    "samples": shown,
                    # The sample as a share of everything these artists have in the collection.
                    "share": (
                        sum(len(s.shown) for s in shown) / sum(s.total for s in shown)
                        if shown
                        else 0.0
                    ),
                }
            )
    return render_template(
        "showcase/index.html",
        showcases=showcases,
        fill_percent=settings.showcase_fill_percent,
        error=request.args.get("error"),
        swapped=request.args.get("swapped"),
    )


@blueprint.post("/swap")
def exchange():
    shown = request.form.get("shown", type=int)
    shelved = request.form.get("shelved", type=int)
    anchor = request.form.get("anchor", "")
    if shown is None or shelved is None or not swap(get_store(), shown, shelved):
        return redirect(
            url_for("showcase.index", error=_("Those two albums can’t be exchanged.")) + f"#{anchor}"
        )
    return redirect(url_for("showcase.index", swapped=1) + f"#{anchor}")
