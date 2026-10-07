"""Read queries behind Browse/Search: the collection in physical shelf order."""

from dataclasses import dataclass

from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    Cabinet,
    Cluster,
    EraBand,
    Placement,
    Shelf,
)
from sleeve_shelf.persistence.store import JsonStore


@dataclass(frozen=True, slots=True)
class ShelfSummary:
    """A shelf as a stop in the crate-digging order."""

    shelf_id: int
    cabinet: str
    shelf: str
    reachability_score: int | None
    album_count: int


@dataclass(frozen=True, slots=True)
class AlbumRow:
    """An album with everything Browse/Search shows about it."""

    album_id: int
    artist: str
    title: str
    year: int | None
    cluster: str | None
    era_band: str | None
    shelf_id: int | None
    cabinet: str | None
    shelf: str | None


class BrowseQueries:
    """Shelf-order and search queries over the stored collection."""

    def __init__(self, store: JsonStore) -> None:
        self._store = store

    def shelves(self) -> list[ShelfSummary]:
        """All shelves in physical order, with how many albums each holds."""
        rows = self._store.query(
            f"""
            {self._located_albums()}
            SELECT shelf.id, cabinet.name, shelf.name, shelf.reachability_score,
                   count(located.album_id)
            FROM {self._store.relation(Shelf)} AS shelf
            JOIN {self._store.relation(Cabinet)} AS cabinet ON cabinet.id = shelf.cabinet_id
            LEFT JOIN located ON located.shelf_id = shelf.id
            GROUP BY cabinet.id, cabinet.name, shelf.id, shelf.name, shelf.reachability_score
            ORDER BY cabinet.id, shelf.id
            """
        )
        return [ShelfSummary(*row) for row in rows]

    def shelf_albums(self, shelf_id: int) -> list[AlbumRow]:
        """The albums on one shelf, in the order they stand there."""
        return self._albums("WHERE shelf_id = ?", [shelf_id])

    def unplaced(self) -> list[AlbumRow]:
        """Albums without a spot on any shelf."""
        return self._albums("WHERE shelf_id IS NULL", [])

    def search(self, text: str) -> list[AlbumRow]:
        """Albums whose artist or title contains every word of the text."""
        terms = text.split()
        if not terms:
            return []
        condition = " AND ".join(
            "contains(strip_accents(lower(artist || ' ' || title)), strip_accents(lower(?)))"
            for _ in terms
        )
        return self._albums(f"WHERE {condition}", terms)

    def _albums(self, where: str, parameters: list) -> list[AlbumRow]:
        rows = self._store.query(
            f"""
            {self._located_albums()}
            SELECT album_id, artist, title, year, cluster, era_band, shelf_id, cabinet, shelf
            FROM located
            {where}
            ORDER BY cabinet_id NULLS LAST, shelf_id, position, title, album_id
            """,
            parameters,
        )
        return [AlbumRow(*row) for row in rows]

    def _located_albums(self) -> str:
        """CTE resolving each album's location: its own placement, else its era band's,
        else its artist's."""
        relation = self._store.relation
        return f"""
            WITH placement AS (SELECT * FROM {relation(Placement)}),
            located AS (
                SELECT album.id AS album_id, artist.name AS artist, album.title,
                       album.original_release_year AS year, cluster.name AS cluster,
                       era_band.label AS era_band, shelf.id AS shelf_id,
                       cabinet.id AS cabinet_id, cabinet.name AS cabinet, shelf.name AS shelf,
                       coalesce(own.position, band.position, whole.position) AS position
                FROM {relation(Album)} AS album
                JOIN {relation(Artist)} AS artist ON artist.id = album.artist_id
                LEFT JOIN {relation(EraBand)} AS era_band ON era_band.id = album.era_band_id
                LEFT JOIN {relation(ArtistClusterAssignment)} AS assignment
                    ON assignment.artist_id = artist.id
                LEFT JOIN {relation(Cluster)} AS cluster ON cluster.id = assignment.cluster_id
                LEFT JOIN placement AS own
                    ON own.unit_type = 'album' AND own.unit_id = album.id
                LEFT JOIN placement AS band
                    ON band.unit_type = 'era_band' AND band.unit_id = album.era_band_id
                LEFT JOIN placement AS whole
                    ON whole.unit_type = 'artist' AND whole.unit_id = album.artist_id
                LEFT JOIN {relation(Shelf)} AS shelf
                    ON shelf.id = coalesce(own.shelf_id, band.shelf_id, whole.shelf_id)
                LEFT JOIN {relation(Cabinet)} AS cabinet ON cabinet.id = shelf.cabinet_id
            )
        """
