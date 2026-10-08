"""Discogs: importing the collection export, enriching it, and confirming proposed matches."""

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
    reject_match,
)
from sleeve_shelf.config import load_settings, save_settings
from sleeve_shelf.domain import Album, Artist, MatchProposal, ReleaseEnrichment
from sleeve_shelf.ingestion.discogs_api import DiscogsClient
from sleeve_shelf.ingestion.discogs_csv import CollectionItem, read_collection
from sleeve_shelf.web.context import get_store
from sleeve_shelf.web.jobs import EnrichmentJob

blueprint = Blueprint("discogs", __name__, url_prefix="/discogs")

PENDING_EXPORT = "pending_export.csv"


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


@blueprint.get("/")
def index(error: str | None = None, token_error: str | None = None, status: int = 200):
    store = get_store()
    settings = load_settings(_data_dir())
    albums = store.load(Album)
    artists = {artist.id: artist.name for artist in store.load(Artist)}
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
    return (
        render_template(
            "discogs/index.html",
            album_count=len(albums),
            linked_count=sum(album.release_id is not None for album in albums),
            fetched_count=len(linked & fetched),
            to_fetch_count=len(linked - fetched),
            proposals=proposals,
            masked_token=f"••••{token[-4:]}" if token else None,
            job=_job().status(),
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
    return render_template("discogs/preview.html", outcome=outcome)


@blueprint.post("/import/confirm")
def confirm_import():
    pending = _data_dir() / PENDING_EXPORT
    if not pending.exists():
        return redirect(url_for("discogs.index"))
    try:
        items = _read(pending)
    except ValueError as error:
        return index(error=str(error), status=400)
    finally:
        pending.unlink(missing_ok=True)
    settings = load_settings(_data_dir())
    import_discogs_collection(get_store(), items, settings.width_constants)
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
