"""Application services for album widths: estimated from the format, or measured by hand."""

from sleeve_shelf.domain import Album, WidthConstants
from sleeve_shelf.persistence import JsonStore


def estimate_widths(albums: list[Album], constants: WidthConstants) -> None:
    """Compute each album's width from its format; compound formats await a manual width.

    Args:
        albums: The albums; changed in place.
        constants: The width figures.
    """
    for album in albums:
        if album.format_tokens is None:
            continue
        album.computed_width_cm = round(album.format_tokens.estimated_width_cm(constants), 2)
        album.width_confirmed = (
            not album.format_tokens.is_compound or album.manual_width_cm is not None
        )


def apply_width_constants(store: JsonStore, constants: WidthConstants) -> None:
    """Estimate every album's width again after the constants changed; shelf widths stay.

    Args:
        store: The store of the collection.
        constants: The width figures.
    """
    if not store.exists(Album):
        return
    albums = store.load(Album)
    estimate_widths(albums, constants)
    store.save(Album, albums)


def set_measured_width(store: JsonStore, album_id: int, width_cm: float | None) -> None:
    """Set an album's width as measured.

    A compound format (a box set, a bundle) awaits a measured width again when it is cleared.

    Args:
        store: The store of the collection.
        album_id: The album.
        width_cm: The width; None goes back to the estimate.

    Raises:
        ValueError: The width is not above zero.
    """
    if width_cm is not None and width_cm <= 0:
        raise ValueError("A width is above zero")
    albums = store.load(Album)
    for album in albums:
        if album.id == album_id:
            album.manual_width_cm = width_cm
            compound = bool(album.format_tokens and album.format_tokens.is_compound)
            album.width_confirmed = width_cm is not None or not compound
    store.save(Album, albums)
