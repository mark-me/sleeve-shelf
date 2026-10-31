"""Application settings, kept in config.yaml inside the data directory."""

import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import yaml

from sleeve_shelf.domain import WidthConstants

CONFIG_FILE = "config.yaml"


# Labels that reissue others' records, or are a large company's name on them: that two artists
# are on one says nothing about the two. A first list, to be changed under Settings.
REISSUE_LABELS = (
    "BMG",
    "Craft Recordings",
    "DOL",
    "Jazz Images",
    "Legacy",
    "Light In The Attic",
    "Music On Vinyl",
    "Not Now Music",
    "Original Jazz Classics",
    "Sam Records",
    "Sony Music",
    "UMC",
    "UMe",
    "Universal Music Group",
    "Universal Music Group International",
    "Vinyl Passion",
    "WaxTime",
    "WaxTime In Color",
)


@dataclass(slots=True)
class Settings:
    """Scalar settings; the file holds a credential and is never committed.

    Attributes:
        discogs_token: The token for the Discogs API, if one was entered.
        base_width_cm: The width of one disc.
        surcharge_180_gram_cm: What a 180 gram disc adds.
        surcharge_gatefold_cm: What a gatefold sleeve adds.
        count_bonus_discs_as_vinyl: Whether a vinyl disc anywhere in a release makes it vinyl.
        showcase_fill_percent: The part of a showcase shelf's width albums may take, leaving room to
            flip through them.
        shelf_room_percent: The part of each shelf's width a proposal leaves free, so a few
            purchases later do not set a whole cabinet moving.
        table_records: How many records may be out of the cabinets at once when reorganising: a
            table full.
        sideman_bands: A person in more bands of the collection than this is a sideman: their bands
            are not suggested as their family, and connect to them only loosely.
        labels_left_out: Labels that tie no artists on the Connections screen.
        owner_password_hash: The owner's password, hashed; without one the app is open and everyone
            is the owner.
        owner_login_key: What a logged-in device keeps in its session: random, made anew with every
            password, so changing the password logs out the other devices. Nothing in it comes from
            the password itself.
    """

    discogs_token: str | None = None
    base_width_cm: float = 0.5
    surcharge_180_gram_cm: float = 0.15
    surcharge_gatefold_cm: float = 0.2
    count_bonus_discs_as_vinyl: bool = True
    showcase_fill_percent: int = 60
    shelf_room_percent: int = 10
    table_records: int = 50
    sideman_bands: int = 4
    labels_left_out: list[str] = field(default_factory=lambda: list(REISSUE_LABELS))
    owner_password_hash: str | None = None
    owner_login_key: str | None = None

    @property
    def width_constants(self) -> WidthConstants:
        """The width settings as the sorting and the width estimates use them."""
        return WidthConstants(
            self.base_width_cm, self.surcharge_180_gram_cm, self.surcharge_gatefold_cm
        )


def data_directory(given: str | Path | None = None) -> Path:
    """The data directory: as given, else as the environment says, else `data`.

    Args:
        given: The directory, if the caller names one.

    Returns:
        The directory as an absolute path.
    """
    return Path(given or os.environ.get("SLEEVE_SHELF_DATA_DIR", "data")).resolve()


def load_settings(data_dir: str | Path) -> Settings:
    """Read config.yaml; anything missing keeps its default.

    Args:
        data_dir: The data directory.

    Returns:
        The settings.
    """
    path = Path(data_dir) / CONFIG_FILE
    if not path.exists():
        return Settings()
    stored = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    known = {field.name for field in fields(Settings)}
    return Settings(**{key: value for key, value in stored.items() if key in known})


def save_settings(data_dir: str | Path, settings: Settings) -> None:
    """Write config.yaml whole, readable by the app's own user only.

    It holds the Discogs token and the hash of the owner's password.

    Args:
        data_dir: The data directory.
        settings: The settings to write.
    """
    path = Path(data_dir) / CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.unlink(missing_ok=True)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(yaml.safe_dump(asdict(settings), sort_keys=False))
    os.replace(temporary, path)


def protect_settings(data_dir: str | Path) -> None:
    """Make a config.yaml written before this readable by the app's own user only.

    Args:
        data_dir: The data directory.
    """
    path = Path(data_dir) / CONFIG_FILE
    if path.exists() and path.stat().st_mode & 0o077:
        os.chmod(path, 0o600)
