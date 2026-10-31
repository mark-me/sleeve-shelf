"""What the Dashboard says about the collection at a glance."""

from sleeve_shelf.domain import Album, Cabinet, Cluster, LocationRule, Placement, ReleaseEnrichment, Shelf
from sleeve_shelf.library.taking_part import albums_taking_part
from sleeve_shelf.library.versions import list_versions
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.shelving.proposal import has_proposal


def collection_figures(store: JsonStore) -> dict:
    albums = store.load(Album)
    shelves = store.load(Shelf)
    sorted_albums = albums_taking_part(store)
    versions = list_versions(store)
    fetched = {release.release_id for release in store.load(ReleaseEnrichment)}
    return {
        "has_albums": bool(albums),
        "album_count": len(sorted_albums),
        "placed_count": len({p.album_id for p in store.load(Placement)}),
        "single_count": len(albums) - len(sorted_albums),
        "artist_count": len({album.artist_id for album in sorted_albums}),
        "cluster_count": len(store.load(Cluster)),
        "cabinet_count": len(store.load(Cabinet)),
        "shelf_count": len(shelves),
        "rule_count": len(store.load(LocationRule)),
        "to_fetch": len({a.release_id for a in albums if a.release_id is not None} - fetched),
        "unmeasured": sum(1 for s in shelves if not s.width_cm and not s.is_showcase),
        "has_proposal": has_proposal(store),
        "last_version": versions[0] if versions else None,
        "unsaved": not any(version.is_current for version in versions),
    }
