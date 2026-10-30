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
    """Scalar settings; the file holds a credential and is never committed."""

    discogs_token: str | None = None
    base_width_cm: float = 0.5
    surcharge_180_gram_cm: float = 0.15
    surcharge_gatefold_cm: float = 0.2
    count_bonus_discs_as_vinyl: bool = True
    # The part of a showcase shelf's width albums may take, leaving room to flip through them.
    showcase_fill_percent: int = 60
    # The part of each shelf's width a proposal leaves free, so a few purchases later do not
    # set a whole cabinet moving.
    shelf_room_percent: int = 10
    # How many records may be out of the cabinets at once when reorganising: a table full.
    table_records: int = 50
    # A person in more bands of the collection than this is a sideman: their bands are not
    # suggested as their family, and connect to them only loosely.
    sideman_bands: int = 4
    # Labels that tie no artists on the Connections screen.
    labels_left_out: list[str] = field(default_factory=lambda: list(REISSUE_LABELS))
    # The owner's password, hashed; without one the app is open and everyone is the owner.
    owner_password_hash: str | None = None
    # What a logged-in device keeps in its session: random, made anew with every password,
    # so changing the password logs out the other devices. Nothing in it comes from the
    # password itself.
    owner_login_key: str | None = None

    @property
    def width_constants(self) -> WidthConstants:
        return WidthConstants(
            self.base_width_cm, self.surcharge_180_gram_cm, self.surcharge_gatefold_cm
        )


def load_settings(data_dir: str | Path) -> Settings:
    """Read config.yaml; anything missing keeps its default."""
    path = Path(data_dir) / CONFIG_FILE
    if not path.exists():
        return Settings()
    stored = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    known = {field.name for field in fields(Settings)}
    return Settings(**{key: value for key, value in stored.items() if key in known})


def save_settings(data_dir: str | Path, settings: Settings) -> None:
    """Write config.yaml whole, readable by the app's own user only: it holds the Discogs
    token and the hash of the owner's password."""
    path = Path(data_dir) / CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.unlink(missing_ok=True)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(yaml.safe_dump(asdict(settings), sort_keys=False))
    os.replace(temporary, path)


def protect_settings(data_dir: str | Path) -> None:
    """Make a config.yaml written before this readable by the app's own user only."""
    path = Path(data_dir) / CONFIG_FILE
    if path.exists() and path.stat().st_mode & 0o077:
        os.chmod(path, 0o600)
