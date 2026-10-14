"""The menu: five sections, and the screens of a section as tabs above the page."""

from dataclasses import dataclass

from flask import Request
from flask_babel import lazy_gettext as _


@dataclass(frozen=True)
class Tab:
    endpoint: str
    # Short: the section is named in the menu, and the page has its own, fuller title.
    label: str
    # The blueprints and endpoints whose pages belong to this tab.
    pages: tuple[str, ...]
    # The key in the menu counts of what waits for the user here.
    count: str | None = None


@dataclass(frozen=True)
class Section:
    # Also the name of the section's icon in static/vendor/menu-icons.svg.
    key: str
    label: str
    tabs: tuple[Tab, ...]
    # Pages that belong to the section without having a tab of their own.
    other_pages: tuple[str, ...] = ()


SECTIONS = (
    Section("overview", _("Dashboard"), (Tab("dashboard.index", _("Dashboard"), ("dashboard",)),)),
    Section(
        "collection",
        _("Collection"),
        (
            Tab("browse.browse", _("Browse / Search"), ("browse.browse",)),
            Tab("browse.unplaced", _("Unplaced"), ("browse.unplaced",), "unplaced"),
            Tab("discogs.index", _("Discogs sync"), ("discogs", "setup"), "discogs"),
        ),
        # An album's page is reached from Browse and from the unplaced albums.
        other_pages=("albums.detail",),
    ),
    Section(
        "shelves",
        _("Shelves"),
        (
            Tab("layout.index", _("Layout"), ("layout",)),
            Tab("proposal.index", _("Proposal"), ("proposal",)),
            Tab("showcase.index", _("Showcase"), ("showcase",)),
            Tab("versions.index", _("Versions"), ("versions",)),
            Tab("storage.index", _("Cabinets"), ("storage", "albums.widths"), "storage"),
        ),
    ),
    Section(
        "sorting",
        _("Sorting"),
        (
            Tab("artists.index", _("Artists"), ("artists",), "artists"),
            Tab("families.index", _("Families"), ("families",), "families"),
            Tab("clusters.index", _("Clusters"), ("clusters",)),
            Tab("rules.index", _("Rules"), ("rules",), "rules"),
        ),
    ),
    Section("settings", _("Settings"), (Tab("settings.index", _("Settings"), ("settings",)),)),
)


def _belongs(pages: tuple[str, ...], request: Request) -> bool:
    return request.blueprint in pages or request.endpoint in pages


def current(request: Request) -> tuple[Section | None, Tab | None]:
    """The section and the tab the page being shown belongs to."""
    for section in SECTIONS:
        for tab in section.tabs:
            if _belongs(tab.pages, request):
                return section, tab
        if _belongs(section.other_pages, request):
            return section, None
    return None, None


def section_count(section: Section, counts: dict[str, int]) -> int:
    """What waits for the user in a section: the counts of its tabs together."""
    return sum(counts.get(tab.count, 0) for tab in section.tabs if tab.count)
