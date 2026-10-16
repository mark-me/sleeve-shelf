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
KEY_BYTES = 32


def has_password(data_dir: str | Path) -> bool:
    return bool(load_settings(data_dir).owner_password_hash)


def check_password(data_dir: str | Path, password: str) -> bool:
    return verified_hash(data_dir, password) is not None


def verified_hash(data_dir: str | Path, password: str) -> str | None:
    """The stored hash the password matches, or None. A login is tied to exactly this hash,
    so a password changed meanwhile cannot lend its successor to an old login."""
    stored = load_settings(data_dir).owner_password_hash
    return stored if stored and check_password_hash(stored, password) else None


def set_password(data_dir: str | Path, password: str) -> str:
    """Set or change the owner's password, returning its hash; ValueError when too short."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"A password has at least {MIN_PASSWORD_LENGTH} characters")
    settings = load_settings(data_dir)
    settings.owner_password_hash = generate_password_hash(password)
    save_settings(data_dir, settings)
    return settings.owner_password_hash


def remove_password(data_dir: str | Path) -> None:
    """Open the app again: no password, everyone the owner."""
    settings = load_settings(data_dir)
    settings.owner_password_hash = None
    save_settings(data_dir, settings)


def session_key(data_dir: str | Path) -> bytes:
    """The key that signs the session cookie, made once per installation and kept in the
    data directory, so a login survives a restart of the app or a new container.

    It is written whole or not at all: a key cut short — by a stop halfway through writing
    it — would be guessable, so one that is not a full key is made anew.
    """
    path = Path(data_dir) / SESSION_KEY_FILE
    key = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    if not _is_full_key(key):
        key = secrets.token_hex(KEY_BYTES)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.unlink(missing_ok=True)
        # Only the owner of the process may read it, from the moment it exists.
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(key)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    return key.encode()


def _is_full_key(key: str) -> bool:
    return len(key) == 2 * KEY_BYTES and all(char in "0123456789abcdef" for char in key)
