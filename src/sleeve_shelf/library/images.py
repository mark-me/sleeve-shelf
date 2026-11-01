"""Images the user adds, of an artist or an album: what they may be, and their small copies."""

import io
from pathlib import Path

from PIL import Image, ImageOps

MAX_IMAGE_BYTES = 5 * 1024 * 1024
# The longest side of the small copy made for lists: twice the 150 px a picture is shown at
# on its page, so it stays sharp on a phone.
THUMB_PIXELS = 300
# What an image file starts with, and the extension it is kept under.
_IMAGE_KINDS = (
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)


def image_extension(data: bytes) -> str | None:
    """The kind of image the bytes are.

    Args:
        data: The bytes.

    Returns:
        The extension for JPEG, PNG, GIF or WebP; None for anything else.
    """
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return next((ext for start, ext in _IMAGE_KINDS if data.startswith(start)), None)


def thumb_name(picture_file: str) -> str:
    """The file the small copy of a picture is kept under, next to the picture itself.

    Args:
        picture_file: The file of the picture.

    Returns:
        The file of its small copy.
    """
    return Path(picture_file).stem + ".thumb.jpg"


def thumbnail(data: bytes) -> bytes | None:
    """A small JPEG copy of an image, upright and without transparency.

    Args:
        data: The bytes of the image.

    Returns:
        The bytes of the copy, or None if the image can't be read.
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((THUMB_PIXELS, THUMB_PIXELS))
            if image.mode != "RGB":
                # JPEG has no transparency: lay the picture on white.
                image = image.convert("RGBA")
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            out = io.BytesIO()
            image.save(out, "JPEG", quality=85, optimize=True)
            return out.getvalue()
    except Exception:  # noqa: BLE001 - whatever is wrong with the file, it is no usable image
        return None
