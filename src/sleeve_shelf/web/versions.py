"""Versions: saved layouts, and going back to one."""

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_babel import ngettext

from sleeve_shelf.library.versions import list_versions, restore_version, save_version
from sleeve_shelf.web.context import get_store

blueprint = Blueprint("versions", __name__, url_prefix="/versions")


@blueprint.get("/")
def index():
    """The Versions screen."""
    versions = list_versions(get_store())
    return render_template(
        "versions/index.html",
        versions=versions,
        unsaved=not any(version.is_current for version in versions),
        message=request.args.get("message"),
    )


@blueprint.post("/save")
def save():
    """Save the current layout as a version."""
    save_version(get_store(), request.form.get("label", "").strip())
    return redirect(url_for("versions.index"))


@blueprint.post("/<name>/restore")
def restore(name: str):
    """Put a saved version back.

    Args:
        name: The version.
    """
    store = get_store()
    if name not in store.snapshots():
        abort(404)
    missing = restore_version(store, name)
    message = _("The version has been put back.")
    if missing:
        message += " " + ngettext(
            "%(num)d album of that version no longer exists or lost its shelf, and was left out.",
            "%(num)d albums of that version no longer exist or lost their shelf, and were left out.",
            missing,
        )
    return redirect(url_for("versions.index", message=message))
