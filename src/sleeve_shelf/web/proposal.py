"""Sorting proposal: generate one, compare it with the current layout, accept or discard it."""

from flask import Blueprint, current_app, redirect, render_template, url_for

from sleeve_shelf.shelving import proposal
from sleeve_shelf.config import load_settings
from sleeve_shelf.web.context import get_store

blueprint = Blueprint("proposal", __name__, url_prefix="/proposal")


@blueprint.get("/")
def index():
    return render_template("proposal/index.html", **proposal.proposal_overview(get_store()))


@blueprint.post("/generate")
def generate():
    settings = load_settings(current_app.config["DATA_DIR"])
    proposal.generate_proposal(get_store(), settings.width_constants, settings.shelf_room_percent)
    return redirect(url_for("proposal.index"))


@blueprint.post("/accept")
def accept():
    proposal.accept_proposal(get_store())
    return redirect(url_for("browse.browse"))


@blueprint.post("/discard")
def discard():
    proposal.discard_proposal(get_store())
    return redirect(url_for("proposal.index"))
