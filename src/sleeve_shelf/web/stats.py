"""Statistics: who and what recurs across the collection, and something to pull from the shelf."""

from datetime import date

from flask import Blueprint, render_template, request

from sleeve_shelf.insights.collection_stats import LONG_AGO_YEARS, collection_figures, from_the_shelf
from sleeve_shelf.insights.ties import Tie
from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.web.context import get_store

blueprint = Blueprint("stats", __name__, url_prefix="/statistics")

# The ties a way goes along here: those the longest way is worked out by.
CLOSE_TIES = ",".join(tie.value for tie in Tie if tie not in (Tie.SONGS, Tie.LABEL, Tie.SESSION))


@blueprint.get("/")
def index():
    store = get_store()
    turn = request.args.get("turn", 0, type=int)
    pick, long_ago = from_the_shelf(store, date.today(), turn)
    return render_template(
        "stats/index.html",
        figures=collection_figures(store),
        # Where each album stands, to take it from the shelf.
        places={row.album_id: row for row in BrowseQueries(store).everything()},
        pick=pick,
        turn=turn,
        long_ago=long_ago,
        long_ago_years=LONG_AGO_YEARS,
        close_ties=CLOSE_TIES,
    )
