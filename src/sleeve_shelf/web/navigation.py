"""The menu: its sections, and the screens of a section as tabs above the page."""

from dataclasses import dataclass, replace

from flask import Request
from flask_babel import lazy_gettext as _


@dataclass(frozen=True)
class Tab:
    """A tab above the page.

    Attributes:
        endpoint: The screen it opens.
        label: Short: the section is named in the menu, and the page has its own, fuller title.
        pages: The blueprints and endpoints whose pages belong to this tab.
        count: The key in the menu counts of what waits for the user here.
        help: Where the user guide explains the screen: "page/#anchor" within the documentation.
    """

    endpoint: str
    label: str
    pages: tuple[str, ...]
    count: str | None = None
    help: str | None = None


# The two blocks of the menu: looking things up, and keeping the collection up to date.
LOOK_UP = "look up"
MANAGE = "manage"


@dataclass(frozen=True)
class Section:
    """A section of the menu.

    Attributes:
        key: Also the name of the section's icon in static/vendor/menu-icons.svg.
        label: What the menu calls it.
        tabs: Its tabs.
        other_pages: Pages that belong to the section without having a tab of their own.
        help: Where the user guide explains it.
        block: The block of the menu it stands in: LOOK_UP or MANAGE.
    """

    key: str
    label: str
    tabs: tuple[Tab, ...]
    other_pages: tuple[str, ...] = ()
    help: str | None = None
    block: str = LOOK_UP


# Looking up and finding something to play, then the upkeep of the collection (decided by Mark
# 2026-11-07); a visitor sees only the first block.
SECTIONS = (
    Section("home", _("Home"), (Tab("home.index", _("Home"), ("home",), help="user/#home"),)),
    Section(
        "browse",
        _("Browse / Search"),
        (Tab("browse.browse", _("Browse / Search"), ("browse.browse",), help="user/browsing/#browse-and-search"),),
        # An album's page is reached from Browse more than from anywhere else.
        other_pages=("albums.detail",),
        help="user/albums-and-artists/#an-albums-page",
    ),
    Section(
        "connections",
        _("Connections"),
        (Tab("connections.index", _("Connections"), ("connections",), help="user/connections/#connections"),),
    ),
    Section("stats", _("Statistics"), (Tab("stats.index", _("Statistics"), ("stats",), help="user/connections/#statistics"),)),
    Section(
        "worklist",
        _("Worklist"),
        (
            Tab("dashboard.index", _("Dashboard"), ("dashboard",), help="user/#a-typical-round"),
            Tab(
                "browse.unplaced",
                _("Unplaced"),
                ("browse.unplaced", "browse.place_all"),
                "unplaced",
                "user/browsing/#albums-without-a-place",
            ),
        ),
        block=MANAGE,
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
        block=MANAGE,
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
        block=MANAGE,
    ),
    Section(
        "discogs",
        _("Discogs"),
        (Tab("discogs.index", _("Discogs sync"), ("discogs", "setup"), "discogs", "user/discogs/"),),
        block=MANAGE,
    ),
    Section(
        "settings",
        _("Settings"),
        (Tab("settings.index", _("Settings"), ("settings",), help="user/settings/#settings"),),
        block=MANAGE,
    ),
)


def _belongs(pages: tuple[str, ...], request: Request) -> bool:
    return request.blueprint in pages or request.endpoint in pages


def current(request: Request) -> tuple[Section | None, Tab | None]:
    """The section and the tab the page being shown belongs to.

    Args:
        request: The request.

    Returns:
        The two, each None when the page has none.
    """
    for section in SECTIONS:
        for tab in section.tabs:
            if _belongs(tab.pages, request):
                return section, tab
        if _belongs(section.other_pages, request):
            return section, None
    return None, None


def section_count(section: Section, counts: dict[str, int]) -> int:
    """What waits for the user in a section: the counts of its tabs together.

    Args:
        section: The section.
        counts: The menu counts.

    Returns:
        The number.
    """
    return sum(counts.get(tab.count, 0) for tab in section.tabs if tab.count)


# Pages that share a tab with others but have their own part of the user guide.
PAGE_HELP = {
    "artists.edit": "user/albums-and-artists/#an-artists-page",
    "albums.widths": "user/settings/#album-widths",
    "setup.upload_form": "user/getting-started/#first-start",
    "setup.upload": "user/getting-started/#first-start",
}


def help_target(request: Request, section: Section | None, tab: Tab | None) -> str:
    """The part of the user guide that explains the page being shown, as "page/#anchor".

    Args:
        request: The request.
        section: The section of the page.
        tab: The tab of the page.

    Returns:
        The part.
    """
    if request.endpoint in PAGE_HELP:
        return PAGE_HELP[request.endpoint]
    return (tab and tab.help) or (section and section.help) or "user/"


# The tabs a visitor sees.
VISITOR_TABS = ("home.index", "browse.browse", "connections.index", "stats.index")


def visible_sections(owner: bool) -> tuple[Section, ...]:
    """The menu as the one looking may use it.

    Args:
        owner: Whether it is the owner; a visitor only looks things up: Home, browsing and
            searching, the connections and the statistics.

    Returns:
        The sections.
    """
    if owner:
        return SECTIONS
    visible = (replace(s, tabs=tuple(t for t in s.tabs if t.endpoint in VISITOR_TABS)) for s in SECTIONS)
    return tuple(section for section in visible if section.tabs)
