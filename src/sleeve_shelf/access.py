"""Application services for the owner's access: the password, and the key that signs sessions.

Without a password the app is open, as a single-user app on one's own network: everyone is
the owner. Setting one makes everyone else a visitor, who may only look the collection up.
"""

import os
import secrets
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

from sleeve_shelf.config import load_settings, save_settings

# The app is reachable from the internet: a password has to be a long one.
MIN_PASSWORD_LENGTH = 12
SESSION_KEY_FILE = "session_key"


def has_password(data_dir: str | Path) -> bool:
    return bool(load_settings(data_dir).owner_password_hash)


def check_password(data_dir: str | Path, password: str) -> bool:
    stored = load_settings(data_dir).owner_password_hash
    return bool(stored) and check_password_hash(stored, password)


def set_password(data_dir: str | Path, password: str) -> None:
    """Set or change the owner's password; ValueError when it is too short."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"A password has at least {MIN_PASSWORD_LENGTH} characters")
    settings = load_settings(data_dir)
    settings.owner_password_hash = generate_password_hash(password)
    save_settings(data_dir, settings)


def remove_password(data_dir: str | Path) -> None:
    """Open the app again: no password, everyone the owner."""
    settings = load_settings(data_dir)
    settings.owner_password_hash = None
    save_settings(data_dir, settings)


def session_key(data_dir: str | Path) -> bytes:
    """The key that signs the session cookie, made once per installation and kept in the
    data directory, so a login survives a restart of the app or a new container."""
    path = Path(data_dir) / SESSION_KEY_FILE
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32), encoding="utf-8")
        os.chmod(path, 0o600)
    return path.read_text(encoding="utf-8").strip().encode()
