"""Take the screenshots of the user guide from a running app, on a copy of a data directory.

Run from the repository, after installing the browser once:

    uv run --with playwright python -m playwright install chromium
    uv run --with playwright python docs-site/take_screenshots.py path/to/data

The data directory is copied first, so nothing in it changes. The pictures land in
docs-site/docs/images/screens/, in English and in the light theme; only when every one of them
was taken, so a run that fails leaves the pictures there as they were.
"""

import argparse
import logging
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import Page, sync_playwright
from werkzeug.serving import make_server

from sleeve_shelf.domain import Album, Artist
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.web.app import create_app

OUT = Path(__file__).parent / "docs" / "images" / "screens"
WIDTH, HEIGHT = 1280, 820
# The album and artist the pages show: ones every collection of jazz has, or the first there is.
ALBUM_TITLE = "Kind Of Blue"
ARTIST_NAME = "Miles Davis"


def _first(items: list, wanted, fallback):
    return next((item for item in items if wanted(item)), fallback)


def _shoot(page: Page, into: Path, address: str, name: str, *, wait: int = 600, only: str | None = None) -> None:
    """One screenshot: the window as it opens, or only the part of the page given."""
    page.goto(address)
    page.wait_for_timeout(wait)
    if only:
        page.locator(only).screenshot(path=into / f"{name}.png")
    else:
        page.screenshot(path=into / f"{name}.png")
    print(f"{name}.png  {address}")


def main() -> None:
    """Copy the data, run the app on the copy, and take each screenshot."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("data", type=Path, help="the data directory to copy")
    data = parser.parse_args().data
    if not (data / "albums.json").exists():
        sys.exit(f"No collection in {data}")
    OUT.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temporary:
        copy = Path(temporary) / "data"
        taken = Path(temporary) / "screens"
        taken.mkdir()
        # The artists' own pictures are left out of the copy: they are not needed to show the pages.
        shutil.copytree(data, copy, ignore=shutil.ignore_patterns("artist_pictures", "*.part"))
        store = JsonStore(copy)
        albums, artists = store.load(Album), store.load(Artist)
        album = _first(albums, lambda a: a.title == ALBUM_TITLE, albums[0])
        artist = _first(artists, lambda a: a.name == ARTIST_NAME, artists[0])

        # The pages asked for are listed here, not each request.
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        # Port 0: whichever port is free, so a running app or another run is no obstacle.
        server = make_server("127.0.0.1", 0, create_app(copy))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                context = browser.new_context(
                    base_url=f"http://127.0.0.1:{server.port}",
                    locale="en-GB",
                    color_scheme="light",
                    viewport={"width": WIDTH, "height": HEIGHT},
                )
                # Layout's notice about saving put away, and Browse as the wall of covers.
                context.add_init_script(
                    "try { localStorage.setItem('sleeve-shelf-layout-saved-notice', '1');"
                    " localStorage.setItem('sleeve-shelf-browse-view', 'grid'); } catch (e) {}"
                )
                page = context.new_page()
                _shoot(page, taken, "/dashboard/", "dashboard")
                _shoot(page, taken, "/browse", "browse")
                _shoot(page, taken, f"/albums/{album.id}", "album")
                _shoot(page, taken, f"/connections/?artist={artist.id}", "connections", wait=2500, only="#ss-network-frame")
                _shoot(page, taken, "/layout/", "layout")
                _shoot(page, taken, "/unplaced/place", "place-all")
                browser.close()
        finally:
            server.shutdown()
        # All of them, or none: a run that stopped halfway changes nothing.
        for picture in taken.glob("*.png"):
            shutil.move(picture, OUT / picture.name)


if __name__ == "__main__":
    main()
