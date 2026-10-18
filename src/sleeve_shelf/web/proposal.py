"""Sorting proposal: generate one, compare it with the current layout, accept or discard it."""

from math import ceil

from flask import Blueprint, current_app, redirect, render_template, url_for

from sleeve_shelf import proposal
from sleeve_shelf.alias_groups import family_suggestions
from sleeve_shelf.config import load_settings
from sleeve_shelf.domain import (
    Artist,
    Cabinet,
    Placement,
    ProposedPlacement,
    in_order,
)
from sleeve_shelf.persistence import BrowseQueries
from sleeve_shelf.taking_part import albums_taking_part, kept_shelf_ids, usable_shelves
from sleeve_shelf.web.context import get_store

blueprint = Blueprint("proposal", __name__, url_prefix="/proposal")


@blueprint.get("/")
def index():
    store = get_store()
    usable, skipped = usable_shelves(store)
    kept = kept_shelf_ids(store)
    outside = {cabinet.id for cabinet in store.load(Cabinet) if cabinet.outside_sorting}
    cabinet_names = {cabinet.id: cabinet.name for cabinet in store.load(Cabinet)}
    current = {
        p.album_id: p.shelf_id for p in store.load(Placement)
    }
    albums = albums_taking_part(store)
    context = {
        # What stands on a kept shelf stays there, and is not among the albums to place.
        "taking_part": sum(1 for album in albums if current.get(album.id) not in kept),
        "usable_count": len(usable),
        "skipped": [
            {"cabinet": cabinet_names[s.cabinet_id], "shelf": s, "outside": s.cabinet_id in outside}
            for s in skipped
        ],
        "suggestion_count": len(family_suggestions(store)),
        "has_proposal": proposal.has_proposal(store),
    }
    if not context["has_proposal"]:
        return render_template("proposal/index.html", **context)

    proposed = {p.album_id: p.shelf_id for p in store.load(ProposedPlacement)}
    artist_names = {artist.id: artist.name for artist in store.load(Artist)}
    now_fill = BrowseQueries(store).shelf_fill()
    new_fill = BrowseQueries(store, ProposedPlacement).shelf_fill()
    shelves = usable + skipped
    cabinets = [
        {
            "name": cabinet.name,
            "shelves": [
                {
                    "shelf": shelf,
                    "skipped": shelf in skipped,
                    "kept": shelf.id in kept,
                    "outside": shelf.cabinet_id in outside,
                    "now": now_fill.get(shelf.id, (0, 0.0)),
                    "new": new_fill.get(shelf.id, (0, 0.0)),
                }
                for shelf in in_order([s for s in shelves if s.cabinet_id == cabinet.id])
            ],
        }
        for cabinet in in_order(store.load(Cabinet))
    ]
    left_out = sorted(
        (
            {"artist": artist_names[album.artist_id], "title": album.title,
             "was_placed": album.id in current}
            for album in albums
            if album.id not in proposed
        ),
        key=lambda row: (row["artist"].casefold(), row["title"].casefold()),
    )
    moved_count = sum(1 for album_id, shelf_id in proposed.items() if current.get(album_id) != shelf_id)
    settings = load_settings(current_app.config["DATA_DIR"])
    return render_template(
        "proposal/index.html",
        **context,
        cabinets=cabinets,
        placed_count=len(proposed),
        left_out=left_out,
        moved_count=moved_count,
        staying_count=sum(1 for album_id, shelf_id in proposed.items() if current.get(album_id) == shelf_id),
        # What carrying it out takes: every album that moves passes over the table once.
        table_records=settings.table_records,
        rounds=ceil(moved_count / settings.table_records),
        room_percent=settings.shelf_room_percent,
    )


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
