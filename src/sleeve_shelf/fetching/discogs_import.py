"""Application services for linking the collection to Discogs.

Importing it (a sync or an uploaded export), confirming proposed matches, and albums that left the
Discogs collection.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher

from sleeve_shelf.library.collection import album_key
from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    LocationRule,
    LocationRuleTarget,
    MatchProposal,
    Placement,
    ProposedPlacement,
    WidthConstants,
)
from sleeve_shelf.ingestion.discogs_csv import CollectionItem
from sleeve_shelf.persistence import JsonStore
from sleeve_shelf.library.versions import save_if_unsaved
from sleeve_shelf.library.widths import estimate_widths

# Below this similarity a loaded album and a Discogs release are not even proposed as a match.
PROPOSAL_THRESHOLD = 0.6


@dataclass(frozen=True, slots=True)
class ImportResult:
    """What importing a Discogs export did to the collection.

    Attributes:
        vinyl_count: The vinyl releases in the export.
        skipped_non_vinyl: The other releases, left out.
        matched: Albums linked to their release outright.
        proposed: Matches waiting for confirmation.
        added: New albums, not on a shelf yet.
        unmatched_albums: Albums without a release.
        gone: Artist and title of the albums whose release is no longer in the Discogs collection.
        refreshed: Linked albums whose format was brought up to date.
    """

    vinyl_count: int
    skipped_non_vinyl: int
    matched: int
    proposed: int
    added: int
    unmatched_albums: int
    gone: tuple[tuple[str, str], ...] = ()
    refreshed: int = 0


def _mark_departed(
    albums: list[Album], in_collection: set[int], artist_names: dict[int, str]
) -> list[tuple[str, str]]:
    """Mark the albums whose release left the collection; returns artist and title of those to ask about."""
    gone = []
    for album in albums:
        album.left_discogs = album.release_id is not None and album.release_id not in in_collection
        if not album.left_discogs:
            # Back in the collection: should it leave again, the question is asked anew.
            album.kept_after_discogs = False
        elif not album.kept_after_discogs:
            gone.append((artist_names[album.artist_id], album.title))
    return gone


def _refresh_formats(albums: list[Album], vinyl: list[CollectionItem]) -> int:
    """Give the linked albums the format of their release; returns how many changed."""
    refreshed = 0
    formats = {item.release_id: item.format_tokens for item in vinyl}
    for album in albums:
        current = formats.get(album.release_id)
        if current is not None and album.format_tokens != current:
            album.format_tokens = current
            refreshed += 1
    return refreshed


def _link_by_name(
    albums: list[Album], by_key: dict[tuple[str, str], list[CollectionItem]], artist_names: dict[int, str]
) -> tuple[int, list[Album]]:
    """Link albums to the release of the same artist and title; returns how many, and the rest."""
    matched = 0
    unmatched: list[Album] = []
    for album in albums:
        if album.release_id is not None:
            continue
        candidates = by_key[album_key(artist_names[album.artist_id], album.title)]
        if not candidates:
            unmatched.append(album)
            continue
        # Two pressings of one title are told apart by their format.
        qualifiers = album.format_tokens.qualifiers if album.format_tokens else None
        item = next((c for c in candidates if c.format_tokens.qualifiers == qualifiers), candidates[0])
        candidates.remove(item)
        album.release_id = item.release_id
        if album.format_tokens is None:
            album.format_tokens = item.format_tokens
        matched += 1
    return matched, unmatched


def _propose_matches(
    unmatched: list[Album], remaining: list[CollectionItem], artist_names: dict[int, str]
) -> list[MatchProposal]:
    """For each album left, the release most like it, if alike enough; taken out of remaining."""
    proposals: list[MatchProposal] = []
    for album in unmatched:
        text = f"{artist_names[album.artist_id]} {album.title}".casefold()
        scored = [
            (SequenceMatcher(None, text, f"{item.artist} {item.title}".casefold()).ratio(), item)
            for item in remaining
        ]
        score, item = max(scored, key=lambda pair: pair[0], default=(0.0, None))
        if item is not None and score >= PROPOSAL_THRESHOLD:
            remaining.remove(item)
            proposals.append(
                MatchProposal(
                    album.id,
                    item.release_id,
                    item.artist,
                    item.title,
                    round(score, 3),
                    item.format_tokens,
                    item.cover_url,
                    item.cover_image_url,
                )
            )
    return proposals


def _add_new_albums(
    store: JsonStore, remaining: list[CollectionItem], albums: list[Album], artists: list[Artist]
) -> None:
    """Add the releases no album accounts for, with their artists when those are new."""
    artist_ids = {artist.name: artist.id for artist in artists}
    # A new album of an artist whose cluster is settled is a purchase to weigh against it.
    settled = {a.artist_id for a in store.load(ArtistClusterAssignment) if a.confirmed}
    for item in remaining:
        artist_id = artist_ids.get(item.artist)
        if artist_id is None:
            artist_id = store.next_id(Artist, artists)
            artists.append(Artist(artist_id, item.artist))
            artist_ids[item.artist] = artist_id
        albums.append(
            Album(
                id=store.next_id(Album, albums),
                artist_id=artist_id,
                title=item.title,
                release_id=item.release_id,
                format_tokens=item.format_tokens,
                new_purchase=artist_id in settled,
                added_on=date.today(),
            )
        )


def _take_covers(albums: list[Album], vinyl: list[CollectionItem]) -> None:
    """A cover only comes with a sync; an export leaves the covers as they are."""
    covers = {item.release_id: item.cover_url for item in vinyl if item.cover_url}
    large_covers = {item.release_id: item.cover_image_url for item in vinyl if item.cover_image_url}
    for album in albums:
        if album.release_id in covers:
            album.cover_url = covers[album.release_id]
        if album.release_id in large_covers:
            album.cover_image_url = large_covers[album.release_id]


def _name_artists_on_discogs(artists: list[Artist], albums: list[Album], vinyl: list[CollectionItem]) -> None:
    """Name the artists on Discogs, which only a sync can.

    An artist is the one most of its releases are credited to; releases shared with other artists
    say nothing.
    """
    credited = {item.release_id: item.artist_discogs_id for item in vinyl if item.artist_discogs_id}
    votes: dict[int, Counter] = defaultdict(Counter)
    for album in albums:
        if album.release_id in credited:
            votes[album.artist_id][credited[album.release_id]] += 1
    for artist in artists:
        if artist.id in votes:
            artist.discogs_artist_id = votes[artist.id].most_common(1)[0][0]


def import_discogs_collection(
    store: JsonStore,
    items: list[CollectionItem],
    constants: WidthConstants,
    dry_run: bool = False,
    refresh_formats: bool = False,
) -> ImportResult:
    """Link the stored albums to the releases of a Discogs export, and add what is new.

    Albums and releases with the same artist and title are linked outright. For what is left, a
    similar-looking release is only proposed, to be confirmed by hand. Vinyl releases that no album
    accounts for become new, unplaced albums. Albums whose release the collection no longer holds
    are marked and reported, never removed.

    Args:
        store: The store of the collection.
        items: The releases of the export or the sync.
        constants: The width figures for what is added.
        dry_run: Only report what would happen.
        refresh_formats: The albums already linked take the format of their release — for a sync,
            which knows the format better than an export does.

    Returns:
        What was done, or would be with a dry run.
    """
    albums = store.load(Album)
    artists = store.load(Artist)
    artist_names = {artist.id: artist.name for artist in artists}
    vinyl = [item for item in items if item.is_vinyl]

    known_releases = {album.release_id for album in albums if album.release_id is not None}
    gone = _mark_departed(albums, {item.release_id for item in items}, artist_names)
    refreshed = _refresh_formats(albums, vinyl) if refresh_formats else 0

    by_key: dict[tuple[str, str], list[CollectionItem]] = defaultdict(list)
    for item in vinyl:
        if item.release_id not in known_releases:
            by_key[album_key(item.artist, item.title)].append(item)
    matched, unmatched = _link_by_name(albums, by_key, artist_names)

    remaining = [item for candidates in by_key.values() for item in candidates]
    proposals = _propose_matches(unmatched, remaining, artist_names)
    _add_new_albums(store, remaining, albums, artists)
    _take_covers(albums, vinyl)
    _name_artists_on_discogs(artists, albums, vinyl)

    if not dry_run:
        estimate_widths(albums, constants)
        store.save(Artist, artists)
        store.save(Album, albums)
        store.save(MatchProposal, proposals)
    return ImportResult(
        vinyl_count=len(vinyl),
        skipped_non_vinyl=len(items) - len(vinyl),
        matched=matched,
        proposed=len(proposals),
        added=len(remaining),
        unmatched_albums=len(unmatched) - len(proposals),
        gone=tuple(gone),
        refreshed=refreshed,
    )


def confirm_match(store: JsonStore, album_id: int, constants: WidthConstants) -> None:
    """Accept a proposed match: the album takes the proposed release.

    Args:
        store: The store of the collection.
        album_id: The album.
        constants: The width figures for its new format.
    """
    proposals = store.load(MatchProposal)
    proposal = next((p for p in proposals if p.album_id == album_id), None)
    if proposal is None:
        return
    albums = store.load(Album)
    album = next(album for album in albums if album.id == album_id)
    album.release_id = proposal.release_id
    if album.format_tokens is None:
        album.format_tokens = proposal.format_tokens
    # The cover comes along, so the album need not wait for the next sync to have one.
    album.cover_url = proposal.cover_url or album.cover_url
    album.cover_image_url = proposal.cover_image_url or album.cover_image_url
    estimate_widths([album], constants)
    store.save(Album, albums)
    store.save(MatchProposal, [p for p in proposals if p is not proposal])


def reject_match(store: JsonStore, album_id: int, constants: WidthConstants) -> None:
    """Turn a proposed match down: the release becomes a new, unplaced album of its own.

    Args:
        store: The store of the collection.
        album_id: The album the match was proposed for.
        constants: The width figures for the new album.
    """
    proposals = store.load(MatchProposal)
    proposal = next((p for p in proposals if p.album_id == album_id), None)
    if proposal is None:
        return
    albums = store.load(Album)
    artists = store.load(Artist)
    artist = next((artist for artist in artists if artist.name == proposal.artist), None)
    if artist is None:
        artist = Artist(store.next_id(Artist, artists), proposal.artist)
        artists.append(artist)
    album = Album(
        id=store.next_id(Album, albums),
        artist_id=artist.id,
        title=proposal.title,
        release_id=proposal.release_id,
        format_tokens=proposal.format_tokens,
        cover_url=proposal.cover_url,
        cover_image_url=proposal.cover_image_url,
        new_purchase=any(
            a.artist_id == artist.id and a.confirmed
            for a in store.load(ArtistClusterAssignment)
        ),
        added_on=date.today(),
    )
    estimate_widths([album], constants)
    albums.append(album)
    store.save(Artist, artists)
    store.save(Album, albums)
    store.save(MatchProposal, [p for p in proposals if p is not proposal])


def remove_departed_album(store: JsonStore, album_id: int) -> bool:
    """Remove an album whose release left the Discogs collection; the caller has asked first.

    The album goes, with its place on a shelf (also in a waiting proposal), its own location rule
    and a proposed match. The layout is saved as a version before an album is taken off its shelf.
    The artist stays, even without albums. Any other album is left alone: only one marked as gone
    can be removed here.

    Args:
        store: The store of the collection.
        album_id: The album.

    Returns:
        Whether the album was removed.
    """
    albums = store.load(Album)
    album = next((a for a in albums if a.id == album_id and a.left_discogs), None)
    if album is None:
        return False

    def is_other(placement: Placement) -> bool:
        return placement.album_id != album_id

    placements = store.load(Placement)
    if not all(is_other(placement) for placement in placements):
        save_if_unsaved(store, "before removing an album")
        store.save(Placement, [p for p in placements if is_other(p)])
    if store.exists(ProposedPlacement):
        store.save(ProposedPlacement, [p for p in store.load(ProposedPlacement) if is_other(p)])
    rules = store.load(LocationRule)
    kept_rules = [
        rule
        for rule in rules
        if rule.target_type is not LocationRuleTarget.ALBUM or rule.target_id != album_id
    ]
    if len(kept_rules) != len(rules):
        store.save(LocationRule, kept_rules)
    proposals = store.load(MatchProposal)
    if any(proposal.album_id == album_id for proposal in proposals):
        store.save(MatchProposal, [p for p in proposals if p.album_id != album_id])
    store.save(Album, [a for a in albums if a.id != album_id])
    return True


def keep_departed_album(store: JsonStore, album_id: int, keep: bool = True) -> bool:
    """Note that an album that left the Discogs collection is kept, so it is not asked about again.

    Args:
        store: The store of the collection.
        album_id: The album.
        keep: False takes the note back: the album is listed as gone once more.

    Returns:
        Whether such an album was found.
    """
    albums = store.load(Album)
    album = next((a for a in albums if a.id == album_id and a.left_discogs), None)
    if album is None:
        return False
    album.kept_after_discogs = keep
    store.save(Album, albums)
    return True
