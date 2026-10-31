"""The language of the pages: the browser's, unless chosen for this device under Settings."""

from pathlib import Path

from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po
from flask import Blueprint, request, url_for
from flask_babel import format_decimal

from sleeve_shelf.web.login import redirect_within

blueprint = Blueprint("language", __name__)

# The languages there is a catalogue for, each named in its own language.
LANGUAGES = {"en": "English", "nl": "Nederlands"}
DEFAULT = "en"
# The choice made on this device; without it the browser's languages decide.
COOKIE = "language"
COOKIE_DAYS = 365

TRANSLATIONS = Path(__file__).resolve().parent.parent / "translations"


def select() -> str:
    """The language for this request.

    Returns:
        The one chosen on this device, or else the first of the browser's languages there is a
        catalogue for.
    """
    chosen = request.cookies.get(COOKIE)
    if chosen in LANGUAGES:
        return chosen
    return request.accept_languages.best_match(LANGUAGES, default=DEFAULT)


def compile_catalogues(directory: Path = TRANSLATIONS) -> None:
    """Make the compiled catalogue (.mo) of each language whose .po is newer.

    Flask-Babel reads only those. The Docker image has them made at build time; a folder that cannot
    be written to is left as it is.

    Args:
        directory: The folder of the catalogues.
    """
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


def decimal(value: float, digits: int = 1) -> str:
    """A number as the language writes it: "39.8" in English, "39,8" in Dutch.

    Args:
        value: The number.
        digits: How many decimals.

    Returns:
        The number as text.
    """
    return format_decimal(value, format="#,##0." + "0" * digits if digits else "#,##0")


def editable(value: float) -> str:
    """A number to put in a form field.

    As few decimals as it needs, and no thousands separator, so it is read back as it was (a decimal
    comma is accepted).

    Args:
        value: The number.

    Returns:
        The number as text.
    """
    return format_decimal(value, format="0.###")


@blueprint.post("/language")
def choose():
    """Choose the language for this device, or leave it to the browser again.

    Back to the page it was chosen on (the menu), or to Settings.
    """
    chosen = request.form.get("language", "")
    target = request.form.get("next")
    # From the menu, back to that page (or the start, should it be no page of this app);
    # from Settings, which sends none, back there.
    response = redirect_within(target, url_for("index") if target else url_for("settings.index"))
    if chosen in LANGUAGES:
        response.set_cookie(
            COOKIE, chosen, max_age=COOKIE_DAYS * 24 * 3600, samesite="Lax", httponly=True
        )
    else:
        response.delete_cookie(COOKIE)
    return response
