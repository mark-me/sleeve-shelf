"""Tests for the help: the documentation site within the app, and its link from every screen."""

import re
import unicodedata
from pathlib import Path

import pytest

from sleeve_shelf import create_app
from sleeve_shelf.web.help import ONLINE
from sleeve_shelf.web.navigation import PAGE_HELP, SECTIONS

DOCS = Path(__file__).parent.parent / "docs-site" / "docs"


@pytest.fixture
def site(tmp_path):
    site = tmp_path / "site"
    (site / "user" / "shelves").mkdir(parents=True)
    (site / "index.html").write_text("home")
    (site / "user" / "shelves" / "index.html").write_text("shelves")
    (site / "assets").mkdir()
    (site / "assets" / "main.css").write_text("css")
    return site


def _client(tmp_path, monkeypatch, site):
    monkeypatch.setenv("SLEEVE_SHELF_HELP_DIR", str(site))
    return create_app(tmp_path / "data").test_client()


def test_the_built_site_is_served_under_help(tmp_path, monkeypatch, site):
    client = _client(tmp_path, monkeypatch, site)

    assert client.get("/help/").data == b"home"
    assert client.get("/help/user/shelves/").data == b"shelves"
    assert client.get("/help/assets/main.css").data == b"css"
    # A page without its slash goes to it, so its relative links work.
    assert client.get("/help/user/shelves").headers["Location"] == "/help/user/shelves/"
    assert client.get("/help/user/nothing/").status_code == 404
    assert client.get("/help/../pyproject.toml").status_code == 404


def test_without_a_built_site_the_help_comes_from_github_pages(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, tmp_path / "nowhere")

    assert client.get("/help/user/shelves/").headers["Location"] == ONLINE + "user/shelves/"


def _slug(heading: str) -> str:
    """A heading's anchor as the documentation site makes it: emoji and signs left out."""
    text = unicodedata.normalize("NFKD", heading).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


def test_every_screen_points_to_a_part_of_the_user_guide_that_exists():
    targets = [tab.help for section in SECTIONS for tab in section.tabs]
    targets += [section.help for section in SECTIONS if section.help] + list(PAGE_HELP.values())
    assert all(targets), "a tab without help"

    for target in targets:
        page, _, anchor = target.partition("#")
        # "user/" is user/index.md, "user/browsing/" is user/browsing.md.
        folder = DOCS / page / "index.md"
        source = folder if folder.is_file() else DOCS / (page.rstrip("/") + ".md")
        assert source.is_file(), target
        if anchor:
            text = re.sub(r"```.*?```", "", source.read_text(encoding="utf-8"), flags=re.S)
            anchors = {_slug(line.lstrip("#")) for line in text.splitlines() if line.startswith("#")}
            assert anchor in anchors, f"{target}: no heading with that anchor"


def test_every_screen_links_to_its_part_of_the_guide(tmp_path, monkeypatch, site):
    from openpyxl import Workbook

    client = _client(tmp_path, monkeypatch, site)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Kastindeling"
    sheet.append(["Locatie", "Vak", "Cluster", "Era-band (artiest)", "Artiest", "Titel"])
    sheet.append(["Kast", "a", "Jazz", "voor 1960", "Miles Davis", "Kind Of Blue"])
    path = tmp_path / "layout.xlsx"
    workbook.save(path)
    with path.open("rb") as file:
        client.post("/setup/upload", data={"workbook": (file, "layout.xlsx")})
    client.post("/setup/confirm")

    assert 'class="ss-help-link" href="/help/user/shelves/#layout"' in client.get("/layout/").text
    assert 'href="/help/user/browsing/#an-artists-page"' in client.get("/artists/1").text
    assert 'href="/help/user/settings/#settings"' in client.get("/settings/").text
    assert 'href="/help/user/" class="ss-nav-help" target="sleeve-shelf-help"' in client.get("/dashboard/").text
