"""Reorganise: carrying out a proposal on the real shelves, a table full at a time."""

from flask import Blueprint, redirect, render_template, request, url_for

from sleeve_shelf.config import load_settings
from sleeve_shelf.shelving.reorganising import reorganising_overview, start, stop, tick_off
from sleeve_shelf.web.context import get_store

blueprint = Blueprint("reorganising", __name__, url_prefix="/reorganise")


def _constants():
    return load_settings(get_store().data_dir).width_constants


@blueprint.get("/")
def index():
    """The Reorganise screen: the round at hand, step by step, and how far it is."""
    return render_template(
        "reorganising/index.html",
        changed=request.args.get("changed"),
        stopped=request.args.get("stopped"),
        **reorganising_overview(get_store(), _constants()),
    )


@blueprint.post("/start")
def begin():
    """Start carrying out the waiting proposal."""
    start(get_store(), _constants())
    return redirect(url_for("reorganising.index"))


@blueprint.post("/step")
def step():
    """Tick off the step that was shown; the layout follows it."""
    done = tick_off(get_store(), request.form.get("step", ""), _constants())
    return redirect(url_for("reorganising.index", changed=None if done else 1))


@blueprint.post("/stop")
def end():
    """End the reorganisation: what was done stands, the rest stays where it is."""
    stop(get_store())
    return redirect(url_for("reorganising.index", stopped=1))
