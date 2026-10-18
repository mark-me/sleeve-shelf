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


def test_numbers_are_written_as_the_language_writes_them(tmp_path):
    from sleeve_shelf import create_app

    client = create_app(tmp_path / "data").test_client()
    client.post("/storage/cabinets/new", data={"name": "Kast"})
    client.post("/storage/cabinets/1/shelves/new", data={"name": "a", "width_cm": "35,5", "type": "", "layer": ""})
    dutch = {"Accept-Language": "nl"}

    assert "35.5 cm" in client.get("/storage/").text
    assert "35,5 cm" in client.get("/storage/", headers=dutch).text
    # In a form field too, and what is shown is read back as it was.
    assert 'value="0,5"' in client.get("/settings/", headers=dutch).text
    assert 'value="35,5"' in client.get("/storage/shelves/1", headers=dutch).text


def test_a_visitor_may_choose_the_language_and_the_menu_marks_its_links(tmp_path, monkeypatch):
    from sleeve_shelf import create_app
    from sleeve_shelf.access import set_password

    monkeypatch.setenv("SLEEVE_SHELF_HTTP_LOGIN", "1")
    app = create_app(tmp_path / "data")
    set_password(app.config["DATA_DIR"], "a long and strong one")
    visitor = app.test_client()

    page = visitor.get("/login").text
    assert "#login" in page and "#language" in page and 'value="nl" lang="nl"' in page

    chosen = visitor.post("/language", data={"language": "nl", "next": "/login?next=/browse"})
    assert chosen.status_code == 302 and chosen.headers["Location"] == "/login?next=/browse"
    page = visitor.get("/login").text
    assert "Inloggen" in page and 'value="en" lang="en"' in page
    # Back to a page of this app only, never another site.
    elsewhere = visitor.post("/language", data={"language": "en", "next": "//elsewhere.example"})
    assert elsewhere.headers["Location"] == "/"
    # Choosing the language is all a visitor may send, besides the password.
    assert visitor.post("/storage/cabinets/new", data={"name": "Kast"}).status_code == 403
