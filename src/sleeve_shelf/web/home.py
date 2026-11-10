"""Home: where the app opens, to look something up or find something to play."""

from datetime import date

from flask import Blueprint, render_template, request

from sleeve_shelf.insights.collection_stats import LONG_AGO_YEARS, from_the_shelf, recently_added
from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.web.context import get_store

blueprint = Blueprint("home", __name__)


@blueprint.get("/")
def index():
    """The Home screen: a search, something from the shelf today, and what came in last."""
    store = get_store()
    turn = request.args.get("turn", 0, type=int)
    pick, long_ago = from_the_shelf(store, date.today(), turn)
    recent = recently_added(store)
    return render_template(
        "home/index.html",
        pick=pick,
        turn=turn,
        long_ago=long_ago,
        long_ago_years=LONG_AGO_YEARS,
        recent=recent,
        # Where each album stands, to take it from the shelf.
        places=BrowseQueries(store).albums({pick, *long_ago, *recent} - {None}),
    )
