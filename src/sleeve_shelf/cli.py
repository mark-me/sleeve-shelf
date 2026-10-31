"""The command line: run the app, or do from a terminal what a browser may not be able to."""

import argparse
import getpass
import os
from pathlib import Path

from sleeve_shelf.access import remove_password, set_password
from sleeve_shelf.library.artists import set_picture
from sleeve_shelf.library.collection import load_layout
from sleeve_shelf.config import data_directory, load_settings
from sleeve_shelf.fetching.discogs_import import import_discogs_collection
from sleeve_shelf.domain import Artist
from sleeve_shelf.fetching.enrichment import enrich_collection
from sleeve_shelf.ingestion.discogs_api import DiscogsClient, DiscogsError
from sleeve_shelf.ingestion.discogs_csv import read_collection
from sleeve_shelf.ingestion.initial_load import load_initial_layout
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.web.app import create_app


def main(arguments: list[str] | None = None) -> None:
    """Run the app with Flask's built-in server, or load a workbook from the command line."""
    parser = argparse.ArgumentParser(prog="sleeve-shelf")
    commands = parser.add_subparsers(dest="command")
    load = commands.add_parser(
        "load", help="load a layout workbook; once a collection exists only the layout changes"
    )
    load.add_argument("workbook", type=Path)
    import_discogs = commands.add_parser(
        "import-discogs", help="link the collection to a Discogs CSV export"
    )
    import_discogs.add_argument("export", type=Path)
    commands.add_parser("enrich", help="fetch styles, original years, tracklists and pictures from Discogs")
    set_picture_command = commands.add_parser(
        "set-picture", help="add your own picture of an artist, for when a browser can't upload"
    )
    set_picture_command.add_argument("artist")
    set_picture_command.add_argument("image", type=Path)
    password_command = commands.add_parser(
        "set-password", help="set the owner's password (also when it was forgotten); visitors may then only look"
    )
    password_command.add_argument("--remove", action="store_true", help="open the app again: no password")
    options = parser.parse_args(arguments)

    data_dir = data_directory()
    settings = load_settings(data_dir)
    store = JsonStore(data_dir)

    if options.command == "load":
        # Same effect as the upload in the wizard, for when a browser can't upload.
        result = load_initial_layout(options.workbook, settings.base_width_cm)
        load_layout(store, result, settings.width_constants)
        print(
            f"Loaded {len(result.albums)} albums on {len(result.shelves)} shelves"
            f" into {data_dir}"
        )
        return

    if options.command == "import-discogs":
        items = read_collection(options.export, settings.count_bonus_discs_as_vinyl)
        outcome = import_discogs_collection(store, items, settings.width_constants)
        print(
            f"{outcome.vinyl_count} vinyl releases ({outcome.skipped_non_vinyl} other skipped):"
            f" {outcome.matched} linked to loaded albums, {outcome.proposed} proposed for"
            f" confirmation, {outcome.added} added as new albums;"
            f" {outcome.unmatched_albums} loaded albums have no release."
        )
        return

    if options.command == "set-picture":
        name = options.artist.casefold()
        artist = next((a for a in store.load(Artist) if a.name.casefold() == name), None)
        if artist is None:
            parser.exit(1, f"No artist is called {options.artist!r}\n")
        if not set_picture(store, artist.id, options.image.read_bytes()):
            parser.exit(1, "That file is not a JPEG, PNG, GIF or WebP image of at most 5 MB\n")
        print(f"Picture of {artist.name} set")
        return

    if options.command == "set-password":
        if options.remove:
            remove_password(data_dir)
            print("Password removed: the app is open, everyone can change everything.")
            return
        password = getpass.getpass("New password: ")
        if password != getpass.getpass("Again: "):
            parser.exit(1, "The two passwords differ\n")
        try:
            set_password(data_dir, password)
        except ValueError as error:
            parser.exit(1, f"{error}\n")
        print("Password set: visitors may look the collection up; changing it needs the login.")
        return

    if options.command == "enrich":
        if not settings.discogs_token:
            parser.exit(1, f"No Discogs token in {data_dir / 'config.yaml'}\n")

        def show(done: int, total: int) -> None:
            if done % 20 < 2 or done >= total:
                print(f"{done} of about {total} lookups", flush=True)

        try:
            lookups = enrich_collection(store, DiscogsClient(settings.discogs_token), show)
        except DiscogsError as error:
            parser.exit(1, f"Stopped: {error} Run it again to continue.\n")
        print(f"Enrichment complete after {lookups} lookups.")
        return

    create_app().run(
        host=os.environ.get("SLEEVE_SHELF_HOST", "127.0.0.1"),
        port=int(os.environ.get("SLEEVE_SHELF_PORT", "5000")),
    )
