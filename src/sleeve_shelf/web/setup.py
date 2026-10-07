"""Onboarding wizard for first use: welcome, then the initial load."""

from collections import Counter
from pathlib import Path
from zipfile import BadZipFile

from flask import Blueprint, current_app, redirect, render_template, request, url_for
from flask_babel import gettext as _
from openpyxl.utils.exceptions import InvalidFileException

from sleeve_shelf.collection import replace_collection
from sleeve_shelf.ingestion.initial_load import InitialLoad, load_initial_layout
from sleeve_shelf.web.context import get_store, has_collection

blueprint = Blueprint("setup", __name__, url_prefix="/setup")

PENDING_UPLOAD = "pending_upload.xlsx"


def _pending_path() -> Path:
    return current_app.config["DATA_DIR"] / PENDING_UPLOAD


def _read(path: Path) -> InitialLoad:
    """Load the workbook, turning anything unreadable into a message for the user."""
    try:
        return load_initial_layout(path)
    except (InvalidFileException, BadZipFile, KeyError, OSError) as error:
        raise ValueError(_("This file could not be read as an Excel workbook (.xlsx).")) from error


@blueprint.get("/")
def welcome():
    return render_template("setup/welcome.html")


@blueprint.get("/upload")
def upload_form():
    return render_template("setup/upload.html", has_collection=has_collection())


@blueprint.post("/upload")
def upload():
    file = request.files.get("workbook")
    if file is None or not file.filename:
        return _upload_error(_("Choose a workbook to upload."))
    pending = _pending_path()
    pending.parent.mkdir(parents=True, exist_ok=True)
    file.save(pending)
    try:
        load = _read(pending)
    except ValueError as error:
        pending.unlink(missing_ok=True)
        return _upload_error(str(error))

    albums_per_shelf = Counter(placement.shelf_id for placement in load.placements)
    cabinets = [
        {
            "name": cabinet.name,
            "shelves": [
                {"name": shelf.name, "albums": albums_per_shelf[shelf.id]}
                for shelf in load.shelves
                if shelf.cabinet_id == cabinet.id
            ],
        }
        for cabinet in load.cabinets
    ]
    return render_template(
        "setup/preview.html",
        cabinets=cabinets,
        album_count=len(load.albums),
        artist_count=len(load.artists),
        cluster_count=len(load.clusters),
        shelf_count=len(load.shelves),
        unplaced_count=len(load.albums) - len(load.placements),
        has_collection=has_collection(),
    )


@blueprint.post("/confirm")
def confirm():
    pending = _pending_path()
    if not pending.exists():
        return redirect(url_for("setup.upload_form"))
    try:
        load = _read(pending)
    except ValueError as error:
        return _upload_error(str(error))
    finally:
        pending.unlink(missing_ok=True)
    replace_collection(get_store(), load)
    return redirect(url_for("browse.browse"))


def _upload_error(message: str):
    return (
        render_template("setup/upload.html", error=message, has_collection=has_collection()),
        400,
    )
