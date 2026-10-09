"""Discogs: syncing or importing the collection, enriching it, and confirming matches."""

import json
from math import ceil
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_babel import gettext as _

from sleeve_shelf.collection import (
    confirm_match,
    import_discogs_collection,
    keep_departed_album,
    reject_match,
    remove_departed_album,
)
from sleeve_shelf.config import load_settings, save_settings
from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistEnrichment,
    Cabinet,
    MatchProposal,
    Placement,
    ReleaseEnrichment,
    Shelf,
)
from sleeve_shelf.ingestion.discogs_api import (
    SECONDS_BETWEEN_REQUESTS,
    DiscogsClient,
    DiscogsError,
    collection_items,
)
from sleeve_shelf.ingestion.discogs_csv import CollectionItem, read_collection
from sleeve_shelf.web.context import get_store
from sleeve_shelf.web.jobs import EnrichmentJob

blueprint = Blueprint("discogs", __name__, url_prefix="/discogs")

PENDING_EXPORT = "pending_export.csv"
PENDING_SYNC = "pending_sync.json"


def _data_dir() -> Path:
    return current_app.config["DATA_DIR"]


def _job() -> EnrichmentJob:
    return current_app.extensions.setdefault("enrichment_job", EnrichmentJob())


def _read(path: Path) -> list[CollectionItem]:
    """Read the export, turning anything unreadable into a message for the user."""
    settings = load_settings(_data_dir())
    try:
        return read_collection(path, settings.count_bonus_discs_as_vinyl)
    except (UnicodeDecodeError, OSError) as error:
        raise ValueError(_("This file could not be read as a Discogs CSV export.")) from error


def _pending_items() -> tuple[list[CollectionItem], bool] | None:
    """The collection waiting for confirmation, and whether it comes from a sync."""
    settings = load_settings(_data_dir())
    synced = _data_dir() / PENDING_SYNC
    if synced.exists():
        releases = json.loads(synced.read_text(encoding="utf-8"))
        return collection_items(releases, settings.count_bonus_discs_as_vinyl), True
    if (_data_dir() / PENDING_EXPORT).exists():
        return _read(_data_dir() / PENDING_EXPORT), False
    return None


def _clear_pending() -> None:
    for name in (PENDING_EXPORT, PENDING_SYNC):
        (_data_dir() / name).unlink(missing_ok=True)


@blueprint.get("/")
def index(error: str | None = None, token_error: str | None = None, status: int = 200):
    store = get_store()
    settings = load_settings(_data_dir())
    albums = store.load(Album)
    artist_list = store.load(Artist)
    artists = {artist.id: artist.name for artist in artist_list}
    fetched = {release.release_id for release in store.load(ReleaseEnrichment)}
    linked = {album.release_id for album in albums if album.release_id is not None}
    by_id = {album.id: album for album in albums}
    proposals = [
        {
            "proposal": proposal,
            "album_artist": artists.get(by_id[proposal.album_id].artist_id, ""),
            "album_title": by_id[proposal.album_id].title,
        }
        for proposal in store.load(MatchProposal)
        if proposal.album_id in by_id
    ]
    token = settings.discogs_token
    named = {a.discogs_artist_id for a in artist_list if a.discogs_artist_id is not None}
    pictured = {picture.discogs_artist_id for picture in store.load(ArtistEnrichment)}
    job = _job().status()
    gone = [
        {"album": album, "artist": artists.get(album.artist_id, "")}
        for album in albums
        if album.left_discogs and not album.kept_after_discogs
    ]
    kept = [
        {"album": album, "artist": artists.get(album.artist_id, "")}
        for album in albums
        if album.left_discogs and album.kept_after_discogs
    ]
    return (
        render_template(
            "discogs/index.html",
            album_count=len(albums),
            linked_count=sum(album.release_id is not None for album in albums),
            fetched_count=len(linked & fetched),
            to_fetch_count=len(linked - fetched),
            # A preview that was left without taking it over or importing it.
            waiting="sync" if (_data_dir() / PENDING_SYNC).exists()
            else "export" if (_data_dir() / PENDING_EXPORT).exists()
            else None,
            pictures_to_fetch_count=len(named - pictured),
            # How far each part is, as [done, total]; a running job knows it more precisely.
            albums_progress=job["albums"] or [len(linked & fetched), len(linked)],
            pictures_progress=job["pictures"] or [len(named & pictured), len(named)],
            unnamed_count=sum(artist.discogs_artist_id is None for artist in artist_list),
            minutes=ceil(
                (2 * len(linked - fetched) + len(named - pictured)) * SECONDS_BETWEEN_REQUESTS / 60
            ),
            minutes_left=ceil((job["total"] - job["done"]) * SECONDS_BETWEEN_REQUESTS / 60),
            seconds_per_lookup=SECONDS_BETWEEN_REQUESTS,
            proposals=proposals,
            gone=gone,
            kept=kept,
            masked_token=f"••••{token[-4:]}" if token else None,
            job=job,
            error=error,
            token_error=token_error,
        ),
        status,
    )


@blueprint.post("/import")
def upload():
    file = request.files.get("export")
    if file is None or not file.filename:
        return index(error=_("Choose your Discogs export to upload."), status=400)
    pending = _data_dir() / PENDING_EXPORT
    pending.parent.mkdir(parents=True, exist_ok=True)
    _clear_pending()
    file.save(pending)
    try:
        items = _read(pending)
        if not items:
            raise ValueError(_("No releases were found in this file."))
    except ValueError as error:
        pending.unlink(missing_ok=True)
        return index(error=str(error), status=400)
    settings = load_settings(_data_dir())
    outcome = import_discogs_collection(get_store(), items, settings.width_constants, dry_run=True)
    return render_template("discogs/preview.html", outcome=outcome, synced=False)


@blueprint.post("/sync")
def sync():
    """Fetch the collection from Discogs and preview what taking it over would do."""
    settings = load_settings(_data_dir())
    if not settings.discogs_token:
        return index(error=_("Set your Discogs token first."), status=400)
    if _job().running:
        # Both would draw on the same rate limit.
        return index(error=_("Wait for the fetching to finish, or stop it, before syncing."), status=409)
    factory = current_app.config.get("DISCOGS_CLIENT_FACTORY", DiscogsClient)
    try:
        releases = factory(settings.discogs_token).collection()
    except DiscogsError as error:
        return index(error=str(error), status=502)
    if not releases:
        return index(error=_("Your Discogs collection is empty."), status=400)
    _data_dir().mkdir(parents=True, exist_ok=True)
    _clear_pending()
    (_data_dir() / PENDING_SYNC).write_text(json.dumps(releases), encoding="utf-8")
    items = collection_items(releases, settings.count_bonus_discs_as_vinyl)
    outcome = import_discogs_collection(
        get_store(), items, settings.width_constants, dry_run=True, refresh_formats=True
    )
    return render_template("discogs/preview.html", outcome=outcome, synced=True)


@blueprint.post("/import/confirm")
def confirm_import():
    try:
        pending = _pending_items()
    except ValueError as error:
        return index(error=str(error), status=400)
    finally:
        _clear_pending()
    if pending is None:
        return redirect(url_for("discogs.index"))
    items, synced = pending
    settings = load_settings(_data_dir())
    # Only a sync knows the format well enough to correct albums that are already linked.
    import_discogs_collection(
        get_store(), items, settings.width_constants, refresh_formats=synced
    )
    return redirect(url_for("discogs.index"))


@blueprint.post("/token")
def save_token():
    token = request.form.get("token", "").strip()
    if not token:
        return index(token_error=_("Paste your Discogs personal access token."), status=400)
    settings = load_settings(_data_dir())
    settings.discogs_token = token
    save_settings(_data_dir(), settings)
    return redirect(url_for("discogs.index") + "#enrich")


@blueprint.post("/enrich/start")
def start_enrichment():
    settings = load_settings(_data_dir())
    if not settings.discogs_token:
        return index(token_error=_("Set your Discogs token first."), status=400)
    factory = current_app.config.get("DISCOGS_CLIENT_FACTORY", DiscogsClient)
    _job().start(_data_dir(), settings.discogs_token, factory)
    return redirect(url_for("discogs.index") + "#enrich")


@blueprint.post("/enrich/stop")
def stop_enrichment():
    _job().stop()
    return redirect(url_for("discogs.index") + "#enrich")


@blueprint.get("/enrich/status")
def enrichment_status():
    return jsonify(_job().status())


@blueprint.post("/matches/<int:album_id>/accept")
def accept_match(album_id: int):
    confirm_match(get_store(), album_id, load_settings(_data_dir()).width_constants)
    return redirect(url_for("discogs.index") + "#matches")


@blueprint.post("/matches/<int:album_id>/reject")
def decline_match(album_id: int):
    reject_match(get_store(), album_id, load_settings(_data_dir()).width_constants)
    return redirect(url_for("discogs.index") + "#matches")


@blueprint.route("/gone/<int:album_id>/remove", methods=["GET", "POST"])
def remove_gone(album_id: int):
    """Ask before removing an album that left the Discogs collection, then remove it."""
    store = get_store()
    album = next((a for a in store.load(Album) if a.id == album_id and a.left_discogs), None)
    if album is None:
        return redirect(url_for("discogs.index") + "#gone")
    if request.method == "POST":
        remove_departed_album(store, album_id)
        return redirect(url_for("discogs.index") + "#gone")
    artists = {artist.id: artist.name for artist in store.load(Artist)}
    return render_template(
        "discogs/remove.html",
        album=album,
        artist=artists.get(album.artist_id, ""),
        place=_place(album_id),
    )


@blueprint.post("/gone/<int:album_id>/keep")
def keep_gone(album_id: int):
    """The user still owns an album that left Discogs: stop asking about it."""
    keep_departed_album(get_store(), album_id)
    return redirect(url_for("discogs.index") + "#gone")


@blueprint.post("/gone/<int:album_id>/ask-again")
def ask_again(album_id: int):
    keep_departed_album(get_store(), album_id, keep=False)
    return redirect(url_for("discogs.index") + "#gone")


def _place(album_id: int) -> str | None:
    """Cabinet and shelf an album stands on by its own placement, if any."""
    store = get_store()
    placement = next(
        (
            p
            for p in store.load(Placement)
            if p.album_id == album_id
        ),
        None,
    )
    shelf = placement and next((s for s in store.load(Shelf) if s.id == placement.shelf_id), None)
    if not shelf:
        return None
    cabinet = next((c.name for c in store.load(Cabinet) if c.id == shelf.cabinet_id), "")
    return f"{cabinet} · {shelf.name}"
