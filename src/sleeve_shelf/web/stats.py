"""Statistics: who and what recurs across the collection."""

from flask import Blueprint, render_template

from sleeve_shelf.insights.collection_stats import collection_figures
from sleeve_shelf.insights.ties import Tie
from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.web.context import get_store

blueprint = Blueprint("stats", __name__, url_prefix="/statistics")

# The ties a way goes along here: those the longest way is worked out by.
CLOSE_TIES = ",".join(tie.value for tie in Tie if tie not in (Tie.SONGS, Tie.LABEL, Tie.SESSION))


@blueprint.get("/")
def index():
    """The Statistics screen."""
    store = get_store()
    return render_template(
        "stats/index.html",
        figures=collection_figures(store),
        # Where each album stands, to take it from the shelf.
        places={row.album_id: row for row in BrowseQueries(store).everything()},
        close_ties=CLOSE_TIES,
    )
