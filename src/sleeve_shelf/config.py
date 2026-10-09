"""Application settings, kept in config.yaml inside the data directory."""

from dataclasses import asdict, dataclass, fields
from pathlib import Path

import yaml

from sleeve_shelf.domain import WidthConstants

CONFIG_FILE = "config.yaml"


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
    path = Path(data_dir) / CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(asdict(settings), sort_keys=False), encoding="utf-8")
