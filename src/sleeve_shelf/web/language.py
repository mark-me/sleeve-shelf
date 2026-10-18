"""The language of the pages: the browser's, unless chosen for this device under Settings."""

from pathlib import Path

from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po
from flask import Blueprint, redirect, request, url_for

blueprint = Blueprint("language", __name__)

# The languages there is a catalogue for, each named in its own language.
LANGUAGES = {"en": "English", "nl": "Nederlands"}
DEFAULT = "en"
# The choice made on this device; without it the browser's languages decide.
COOKIE = "language"
COOKIE_DAYS = 365

TRANSLATIONS = Path(__file__).resolve().parent.parent / "translations"


def select() -> str:
    """The language for this request: the one chosen on this device, or else the first of
    the browser's languages there is a catalogue for."""
    chosen = request.cookies.get(COOKIE)
    if chosen in LANGUAGES:
        return chosen
    return request.accept_languages.best_match(LANGUAGES, default=DEFAULT)


def compile_catalogues(directory: Path = TRANSLATIONS) -> None:
    """Make the compiled catalogue (.mo) of each language whose .po is newer, as Flask-Babel
    reads only those. The Docker image has them made at build time; a folder that cannot be
    written to is left as it is."""
    for source in directory.glob("*/LC_MESSAGES/messages.po"):
        target = source.with_suffix(".mo")
        if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
            continue
        try:
            with source.open("rb") as po:
                catalogue = read_po(po, locale=source.parent.parent.name)
            with target.open("wb") as mo:
                write_mo(mo, catalogue)
        except OSError:
            continue


@blueprint.post("/language")
def choose():
    """Choose the language for this device, or leave it to the browser again."""
    chosen = request.form.get("language", "")
    response = redirect(url_for("settings.index"))
    if chosen in LANGUAGES:
        response.set_cookie(
            COOKIE, chosen, max_age=COOKIE_DAYS * 24 * 3600, samesite="Lax", httponly=True
        )
    else:
        response.delete_cookie(COOKIE)
    return response
