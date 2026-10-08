"""Versions: saved layouts, and going back to one."""

from flask import Blueprint, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_babel import ngettext

from sleeve_shelf.versions import list_versions, restore_version, save_version
from sleeve_shelf.web.context import get_store, has_collection

blueprint = Blueprint("versions", __name__, url_prefix="/versions")


@blueprint.before_request
def require_collection():
    if not has_collection():
        return redirect(url_for("setup.welcome"))


@blueprint.get("/")
def index():
    versions = list_versions(get_store())
    return render_template(
        "versions/index.html",
        versions=versions,
        unsaved=not any(version.is_current for version in versions),
        message=request.args.get("message"),
    )


@blueprint.post("/save")
def save():
    save_version(get_store(), request.form.get("label", "").strip())
    return redirect(url_for("versions.index"))


@blueprint.post("/<name>/restore")
def restore(name: str):
    missing = restore_version(get_store(), name)
    message = _("The version has been put back.")
    if missing:
        message += " " + ngettext(
            "%(num)d album of that version no longer exists or lost its shelf, and was left out.",
            "%(num)d albums of that version no longer exist or lost their shelf, and were left out.",
            missing,
        )
    return redirect(url_for("versions.index", message=message))
