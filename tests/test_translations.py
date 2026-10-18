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


def test_dutch_catalogue_translates_everything_and_keeps_the_placeholders():
    # Copy added in English needs its Dutch too: extract, update, and fill in the msgstr.
    with (TRANSLATIONS / "nl" / "LC_MESSAGES" / "messages.po").open("rb") as file:
        catalogue = read_po(file, locale="nl")
    ids = {message.id for message in catalogue if message.id}
    assert ids == _catalogue_messages(TRANSLATIONS / "messages.pot")
    untranslated = [
        message.id
        for message in catalogue
        if message.id and not (all(message.string) if isinstance(message.id, tuple) else message.string)
    ]
    assert untranslated == []
    assert [(message.id, errors) for message, errors in catalogue.check()] == []


def test_the_browser_s_language_is_followed_unless_one_is_chosen_for_this_device(tmp_path):
    from sleeve_shelf import create_app

    client = create_app(tmp_path / "data").test_client()
    dutch = {"Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8"}

    assert "Welcome to Sleeve & Shelf" in client.get("/setup/").text
    page = client.get("/setup/", headers=dutch).text
    assert "Welkom bij Sleeve & Shelf" in page and '<html lang="nl">' in page
    # A language without a catalogue falls back to English.
    assert "Welcome to" in client.get("/setup/", headers={"Accept-Language": "fr"}).text

    # Chosen under Settings, for this device: it goes before the browser's.
    client.post("/language", data={"language": "en"})
    assert "Welcome to" in client.get("/setup/", headers=dutch).text
    settings = client.get("/settings/", headers=dutch).text
    assert '<option value="en" lang="en" selected>English</option>' in settings
    # And left to the browser again.
    client.post("/language", data={"language": "browser"})
    assert "Welkom bij" in client.get("/setup/", headers=dutch).text
