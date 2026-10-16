"""Help: the documentation site, served within the app under /help/.

The Docker image carries the site, built with Zensical from docs-site/, so the help always
belongs to the version that runs, and works offline. Where no built site is found — a
local run before `zensical build` — the help is taken from GitHub Pages instead.
"""

from pathlib import Path

from flask import Blueprint, current_app, redirect, send_from_directory, url_for

blueprint = Blueprint("help", __name__, url_prefix="/help")

ONLINE = "https://mark-me.github.io/sleeve-shelf/"


def built_site() -> Path | None:
    """The folder of the built documentation site, when there is one."""
    directory = current_app.config.get("HELP_DIR")
    return directory if directory and (Path(directory) / "index.html").is_file() else None


@blueprint.get("/", defaults={"path": ""})
@blueprint.get("/<path:path>")
def page(path: str):
    site = built_site()
    if site is None:
        return redirect(ONLINE + path)
    if path == "" or path.endswith("/"):
        path += "index.html"
    elif (site / path).is_dir():
        # A page is a folder with an index: its links are relative to the folder.
        return redirect(url_for("help.page", path=path + "/"))
    return send_from_directory(site, path)


def help_url(target: str | None) -> str:
    """The address of a part of the user guide, given as "page/#anchor"."""
    page, _, anchor = (target or "user/").partition("#")
    return url_for("help.page", path=page) + (f"#{anchor}" if anchor else "")
