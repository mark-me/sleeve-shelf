"""Statistics: who plays on the most records, which songs recur, and the labels they came out on."""

from flask import Blueprint, render_template

from sleeve_shelf.collection_stats import collection_figures
from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.web.context import get_store

blueprint = Blueprint("stats", __name__, url_prefix="/statistics")


@blueprint.get("/")
def index():
    store = get_store()
    return render_template(
        "stats/index.html",
        figures=collection_figures(store),
        # Where each album stands, to take it from the shelf.
        places={row.album_id: row for row in BrowseQueries(store).everything()},
    )
