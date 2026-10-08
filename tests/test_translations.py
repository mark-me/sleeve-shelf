"""Tests for the translation catalogue: it has to list all UI copy in the code."""

from pathlib import Path

from babel.messages.extract import extract_from_dir
from babel.messages.pofile import read_po

ROOT = Path(__file__).parent.parent
TRANSLATIONS = ROOT / "src" / "sleeve_shelf" / "translations"
# The same sources as babel.cfg.
METHODS = [("src/sleeve_shelf/**.py", "python"), ("src/sleeve_shelf/web/templates/**.html", "jinja2")]


def _catalogue_messages(path: Path) -> set:
    with path.open("rb") as file:
        return {message.id for message in read_po(file) if message.id}


def _source_messages() -> set:
    return {message for _, _, message, _, _ in extract_from_dir(str(ROOT), METHODS)}


def test_template_lists_all_ui_copy():
    # Fails after changing copy without extracting again (see CLAUDE.md, Commands).
    assert _catalogue_messages(TRANSLATIONS / "messages.pot") == _source_messages()


def test_english_catalogue_matches_the_template():
    assert _catalogue_messages(TRANSLATIONS / "en" / "LC_MESSAGES" / "messages.po") == _catalogue_messages(
        TRANSLATIONS / "messages.pot"
    )
