"""Tests for the documentation site: its conventions, and that it agrees with the requirements."""

import re
import tomllib
import unicodedata
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs-site" / "docs"


def _headings() -> list[tuple[str, str]]:
    """Every level-2 heading of the site, with the page it is on; code blocks left out."""
    found = []
    for page in sorted(DOCS.rglob("*.md")):
        text = re.sub(r"```.*?```", "", page.read_text(encoding="utf-8"), flags=re.S)
        found += [(page.relative_to(DOCS).as_posix(), line[3:]) for line in text.splitlines() if line.startswith("## ")]
    return found


def _emoji(heading: str) -> str:
    """The emoji a heading starts with, with any joined parts and variation selectors."""
    mark = heading.split(" ", 1)[0]
    return mark if mark and unicodedata.category(mark[0]) == "So" else ""


def test_every_level_two_heading_starts_with_its_own_emoji():
    headings = _headings()
    assert headings

    missing = [f"{page}: {text}" for page, text in headings if not _emoji(text)]
    assert missing == [], "no emoji at the start"
    seen: dict[str, str] = {}
    for page, text in headings:
        emoji = _emoji(text)
        assert emoji not in seen, f"{emoji} on {page} is also used on {seen[emoji]}"
        seen[emoji] = page


def test_the_navigation_names_every_page_and_only_pages_that_exist():
    config = tomllib.loads((ROOT / "docs-site" / "zensical.toml").read_text(encoding="utf-8"))

    def pages(entries) -> list[str]:
        out = []
        for entry in entries:
            if isinstance(entry, str):
                out.append(entry)
            else:
                for value in entry.values():
                    out += pages(value) if isinstance(value, list) else [value]
        return out

    named = pages(config["project"]["nav"])
    on_disk = sorted(page.relative_to(DOCS).as_posix() for page in DOCS.rglob("*.md"))
    assert sorted(named) == on_disk


def test_the_data_model_diagram_is_the_one_in_the_requirements():
    def diagram(path: Path) -> str:
        return re.search(r"```mermaid\nerDiagram\n.*?\n```", path.read_text(encoding="utf-8"), re.S).group(0)

    assert diagram(DOCS / "developer" / "data-model.md") == diagram(ROOT / "docs" / "requirements.md")
