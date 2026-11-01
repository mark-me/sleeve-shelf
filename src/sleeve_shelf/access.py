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
    """Whether the owner has set a password.

    Args:
        data_dir: The data directory.

    Returns:
        True when a password is set; without one the app is open and everyone is the owner.
    """
    return bool(load_settings(data_dir).owner_password_hash)


def check_password(data_dir: str | Path, password: str) -> bool:
    """Whether this is the owner's password.

    Args:
        data_dir: The data directory.
        password: The password as typed.

    Returns:
        True when it matches.
    """
    return verified_key(data_dir, password) is not None


def verified_key(data_dir: str | Path, password: str) -> str | None:
    """The login key of the password the given one matches.

    The key is read together with the hash it was checked against, so a password changed meanwhile
    cannot lend its successor to an old login. A password set before login keys were kept gets one
    now.

    Args:
        data_dir: The data directory.
        password: The password as typed.

    Returns:
        The login key, or None when the password does not match.
    """
    settings = load_settings(data_dir)
    stored = settings.owner_password_hash
    if not stored or not check_password_hash(stored, password):
        return None
    if not settings.owner_login_key:
        settings.owner_login_key = secrets.token_urlsafe(KEY_BYTES)
        save_settings(data_dir, settings)
    return settings.owner_login_key


def set_password(data_dir: str | Path, password: str) -> str:
    """Set or change the owner's password.

    Every other device is logged out, as its key no longer counts.

    Args:
        data_dir: The data directory.
        password: The new password.

    Returns:
        The new login key.

    Raises:
        ValueError: The password is too short.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"A password has at least {MIN_PASSWORD_LENGTH} characters")
    settings = load_settings(data_dir)
    settings.owner_password_hash = generate_password_hash(password)
    settings.owner_login_key = secrets.token_urlsafe(KEY_BYTES)
    save_settings(data_dir, settings)
    return settings.owner_login_key


def remove_password(data_dir: str | Path) -> None:
    """Open the app again: no password, everyone the owner.

    Args:
        data_dir: The data directory.
    """
    settings = load_settings(data_dir)
    settings.owner_password_hash = None
    settings.owner_login_key = None
    save_settings(data_dir, settings)


def session_key(data_dir: str | Path) -> bytes:
    """The key that signs the session cookie, made once per installation.

    It is kept in the data directory, so a login survives a restart of the app or a new container.
    It is written whole or not at all: a key cut short — by a stop halfway through writing it —
    would be guessable, so one that is not a full key is made anew.

    Args:
        data_dir: The data directory.

    Returns:
        The key.
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
