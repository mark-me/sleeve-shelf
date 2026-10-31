"""Read queries behind Browse/Search: the collection in physical shelf order."""

from dataclasses import dataclass
from datetime import date

from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    Cabinet,
    Cluster,
    EraBand,
    Placement,
    ReleaseEnrichment,
    Shelf,
)
from sleeve_shelf.persistence.store import JsonStore


@dataclass(frozen=True, slots=True)
class ShelfSummary:
    """A shelf as a stop in the crate-digging order.

    Attributes:
        shelf_id: The shelf.
        cabinet: The name of its cabinet.
        shelf: Its name.
        reachability_score: How easily it is reached.
        album_count: How many albums it holds.
        outside_sorting: The cabinet is kept outside the sorting: not part of the sorted collection.
    """

    shelf_id: int
    cabinet: str
    shelf: str
    reachability_score: int | None
    album_count: int
    outside_sorting: bool = False


@dataclass(frozen=True, slots=True)
class AlbumRow:
    """An album with everything Browse/Search shows about it.

    Attributes:
        album_id: The album.
        artist: The artist's name.
        title: The title.
        year: The original year.
        cluster: The cluster's name.
        era_band: The era band's label.
        shelf_id: The shelf it stands on; None without a place.
        cabinet: The name of that shelf's cabinet.
        shelf: The name of that shelf.
        is_lp: Whether it is an LP.
        artist_id: The artist.
        cover_url: The small cover.
        added_on: The day a sync or import added the album; None for one that came with the
            workbook.
        tracks: In search results: the songs that matched, as (position, title), when the artist and
            title alone did not.
    """

    album_id: int
    artist: str
    title: str
    year: int | None
    cluster: str | None
    era_band: str | None
    shelf_id: int | None
    cabinet: str | None
    shelf: str | None
    is_lp: bool = True
    artist_id: int | None = None
    cover_url: str | None = None
    added_on: date | None = None
    tracks: tuple[tuple[str, str], ...] = ()


class BrowseQueries:
    """Shelf-order and search queries over the stored collection.

    Args:
        store: The store of the collection.
        placements: The current layout, or a proposal kept next to it.
    """

    def __init__(self, store: JsonStore, placements: type[Placement] = Placement) -> None:
        self._store = store
        # The current layout, or a proposal kept next to it.
        self._placements = placements

    def shelves(self) -> list[ShelfSummary]:
        """All shelves in physical order, with how many albums each holds.

        Returns:
            The shelves.
        """
        rows = self._store.query(
            f"""
            {self._located_albums()}
            SELECT shelf.id, cabinet.name, shelf.name, shelf.reachability_score,
                   count(located.album_id), coalesce(cabinet.outside_sorting, false)
            FROM {self._store.relation(Shelf)} AS shelf
            JOIN {self._store.relation(Cabinet)} AS cabinet ON cabinet.id = shelf.cabinet_id
            LEFT JOIN located ON located.shelf_id = shelf.id
            GROUP BY cabinet.id, cabinet.name, cabinet.position, cabinet.outside_sorting,
                     shelf.id, shelf.name,
                     shelf.position, shelf.reachability_score
            ORDER BY coalesce(cabinet.position, cabinet.id), cabinet.id,
                     coalesce(shelf.position, shelf.id), shelf.id
            """
        )
        return [ShelfSummary(*row) for row in rows]

    def shelf_fill(self) -> dict[int, tuple[int, float]]:
        """Per shelf that holds anything: the number of albums and their summed width.

        Returns:
            The number and the width in cm, by shelf id.
        """
        rows = self._store.query(
            f"""
            {self._located_albums()}
            SELECT shelf_id, count(*), coalesce(sum(width_cm), 0)
            FROM located
            WHERE shelf_id IS NOT NULL
            GROUP BY shelf_id
            """
        )
        return {shelf_id: (count, width) for shelf_id, count, width in rows}

    def shelf_albums(self, shelf_id: int) -> list[AlbumRow]:
        """The albums on one shelf, in the order they stand there.

        Args:
            shelf_id: The shelf.

        Returns:
            The albums.
        """
        return self._albums("WHERE shelf_id = ?", [shelf_id])

    def artist_albums(self, artist_id: int) -> list[AlbumRow]:
        """All albums of one artist, placed or not.

        Args:
            artist_id: The artist.

        Returns:
            The albums.
        """
        return self._albums("WHERE artist_id = ?", [artist_id])

    def everything(self) -> list[AlbumRow]:
        """Every album, placed or not, in shelf order.

        Returns:
            The albums.
        """
        return self._albums("", [])

    def unplaced(self) -> list[AlbumRow]:
        """Albums without a spot on any shelf: what was added last first, then the rest.

        Returns:
            The albums.
        """
        rows = self._albums("WHERE shelf_id IS NULL", [])
        return sorted(rows, key=lambda row: -(row.added_on.toordinal() if row.added_on else 0))

    def search(self, text: str) -> list[AlbumRow]:
        """Albums whose artist and title contain every word of the text, or with one of its songs.

        Such an album comes with the songs that matched.

        Args:
            text: What was typed.

        Returns:
            The albums.
        """
        terms = text.split()
        if not terms:
            return []

        def every_term(text_sql: str) -> str:
            return " AND ".join(
                f"contains(strip_accents(lower({text_sql})), strip_accents(lower(?)))"
                for _ in terms
            )

        by_album = every_term("located.artist || ' ' || located.title")
        by_song = every_term("located.artist || ' ' || located.title || ' ' || song.title")
        # The songs of each album, from its release, in the order they are on the record.
        songs = f"""
            , song AS (
                SELECT album.id AS album_id, unnest(release.tracklist).title AS title,
                       unnest(release.tracklist).position AS position,
                       unnest(range(len(release.tracklist))) AS number
                FROM {self._store.relation(Album)} AS album
                JOIN {self._store.relation(ReleaseEnrichment)} AS release
                    ON release.release_id = album.release_id
            ),
            found AS (
                SELECT song.album_id,
                       list([coalesce(song.position, ''), song.title] ORDER BY song.number) AS tracks
                FROM song JOIN located ON located.album_id = song.album_id
                WHERE ({by_song}) AND NOT ({by_album})
                GROUP BY song.album_id
            )
        """
        return self._albums(
            f"WHERE ({by_album}) OR found.album_id IS NOT NULL", terms * 3, songs
        )

    def _albums(self, where: str, parameters: list, songs: str = "") -> list[AlbumRow]:
        rows = self._store.query(
            f"""
            {self._located_albums()}
            {songs}
            SELECT located.album_id, artist, title, year, cluster, era_band, shelf_id, cabinet,
                   shelf, is_lp, artist_id, cover_url, added_on,
                   {"found.tracks" if songs else "NULL"}
            FROM located
            {"LEFT JOIN found ON found.album_id = located.album_id" if songs else ""}
            {where}
            ORDER BY cabinet_order NULLS LAST, cabinet_id, shelf_order, shelf_id,
                     position, title, located.album_id
            """,
            parameters,
        )
        return [
            AlbumRow(*row[:-1], tracks=tuple(tuple(track) for track in row[-1] or ()))
            for row in rows
        ]

    def _located_albums(self) -> str:
        """CTE giving each album its location, if it has one."""
        relation = self._store.relation
        return f"""
            WITH placement AS (SELECT * FROM {relation(self._placements)}),
            located AS (
                SELECT album.id AS album_id, artist.name AS artist, artist.id AS artist_id,
                       album.title, album.cover_url, album.added_on,
                       album.original_release_year AS year, cluster.name AS cluster,
                       era_band.label AS era_band, shelf.id AS shelf_id,
                       cabinet.id AS cabinet_id, cabinet.name AS cabinet, shelf.name AS shelf,
                       coalesce(cabinet.position, cabinet.id) AS cabinet_order,
                       coalesce(shelf.position, shelf.id) AS shelf_order,
                       placement.position AS position,
                       coalesce(album.manual_width_cm, album.computed_width_cm) AS width_cm,
                       -- An album whose format is unknown counts as an LP.
                       coalesce(len(list_filter(album.format_tokens.qualifiers,
                           token -> regexp_matches(token, '^([0-9]+x)?LP$'))) > 0, true) AS is_lp
                FROM {relation(Album)} AS album
                JOIN {relation(Artist)} AS artist ON artist.id = album.artist_id
                LEFT JOIN {relation(EraBand)} AS era_band ON era_band.id = album.era_band_id
                LEFT JOIN {relation(ArtistClusterAssignment)} AS assignment
                    ON assignment.artist_id = artist.id
                LEFT JOIN {relation(Cluster)} AS cluster ON cluster.id = assignment.cluster_id
                LEFT JOIN placement ON placement.album_id = album.id
                LEFT JOIN {relation(Shelf)} AS shelf ON shelf.id = placement.shelf_id
                LEFT JOIN {relation(Cabinet)} AS cabinet ON cabinet.id = shelf.cabinet_id
            )
        """
