"""The menu: five sections, and the screens of a section as tabs above the page."""

from dataclasses import dataclass, replace

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
    # Where the user guide explains the screen: "page/#anchor" within the documentation.
    help: str | None = None


@dataclass(frozen=True)
class Section:
    # Also the name of the section's icon in static/vendor/menu-icons.svg.
    key: str
    label: str
    tabs: tuple[Tab, ...]
    # Pages that belong to the section without having a tab of their own.
    other_pages: tuple[str, ...] = ()
    help: str | None = None


SECTIONS = (
    Section("overview", _("Dashboard"), (Tab("dashboard.index", _("Dashboard"), ("dashboard",), help="user/#a-typical-round"),)),
    Section(
        "collection",
        _("Collection"),
        (
            Tab("browse.browse", _("Browse / Search"), ("browse.browse",), help="user/browsing/#browse-and-search"),
            Tab("connections.index", _("Connections"), ("connections",), help="user/browsing/#connections"),
            Tab("stats.index", _("Statistics"), ("stats",), help="user/browsing/#statistics"),
            Tab("browse.unplaced", _("Unplaced"), ("browse.unplaced",), "unplaced", "user/browsing/#albums-without-a-place"),
            Tab("discogs.index", _("Discogs sync"), ("discogs", "setup"), "discogs", "user/discogs/"),
        ),
        # An album's page is reached from Browse and from the unplaced albums.
        other_pages=("albums.detail",),
        help="user/browsing/#an-albums-page",
    ),
    Section(
        "shelves",
        _("Shelves"),
        (
            Tab("layout.index", _("Layout"), ("layout",), help="user/shelves/#layout"),
            Tab("moving.index", _("Move"), ("moving",), help="user/shelves/#move"),
            Tab("proposal.index", _("Proposal"), ("proposal",), help="user/sorting/#the-sorting-proposal"),
            Tab("showcase.index", _("Showcase"), ("showcase",), help="user/shelves/#showcase"),
            Tab("versions.index", _("Versions"), ("versions",), help="user/shelves/#versions"),
            Tab("storage.index", _("Cabinets"), ("storage", "albums.widths"), "storage", "user/shelves/#cabinets-and-shelves"),
        ),
    ),
    Section(
        "sorting",
        # Named Sorting until it held more than what a proposal sorts by (2026-10-18).
        _("Organise"),
        (
            Tab("artists.index", _("Artists"), ("artists",), "artists", "user/sorting/#clusters"),
            Tab("families.index", _("Families"), ("families",), "families", "user/sorting/#artist-families"),
            Tab("clusters.index", _("Clusters"), ("clusters",), help="user/sorting/#clusters"),
            Tab("rules.index", _("Rules"), ("rules",), "rules", "user/sorting/#location-rules"),
        ),
    ),
    Section("settings", _("Settings"), (Tab("settings.index", _("Settings"), ("settings",), help="user/settings/#settings"),)),
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


# Pages that share a tab with others but have their own part of the user guide.
PAGE_HELP = {
    "artists.edit": "user/browsing/#an-artists-page",
    "albums.widths": "user/settings/#album-widths",
    "setup.upload_form": "user/getting-started/#first-start",
    "setup.upload": "user/getting-started/#first-start",
}


def help_target(request: Request, section: Section | None, tab: Tab | None) -> str:
    """The part of the user guide that explains the page being shown, as "page/#anchor"."""
    if request.endpoint in PAGE_HELP:
        return PAGE_HELP[request.endpoint]
    return (tab and tab.help) or (section and section.help) or "user/"


# The tabs a visitor sees.
VISITOR_TABS = ("browse.browse", "connections.index")


def visible_sections(owner: bool) -> tuple[Section, ...]:
    """The menu as the one looking may use it: a visitor only browses, searches and looks at
    the connections."""
    if owner:
        return SECTIONS
    collection = next(section for section in SECTIONS if section.key == "collection")
    return (replace(collection, tabs=tuple(tab for tab in collection.tabs if tab.endpoint in VISITOR_TABS)),)
