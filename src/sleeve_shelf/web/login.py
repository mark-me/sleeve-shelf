"""The owner's login, and what a visitor without one may do.

Closed unless listed: a visitor may open only the pages in VISITOR_PAGES, and only to read
them. Everything else — every change, every other screen, and any screen added later —
asks for the login. Without a password the app is open and everyone is the owner.
"""

import hashlib
import threading
import time
from collections import deque
from collections.abc import Callable
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    abort,
    current_app,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_babel import gettext as _
from werkzeug.wrappers import Response

from sleeve_shelf.access import has_password, verified_hash
from sleeve_shelf.config import load_settings

blueprint = Blueprint("login", __name__)

# What a visitor may open, to read only: looking the collection up, listening, the help.
VISITOR_PAGES = frozenset(
    {
        "index",
        "browse.browse",
        "albums.detail",
        "albums.listen",
        "albums.previews",
        "artists.edit",
        "artists.picture",
        "covers.file",
        "help.page",
        "pwa.manifest",
        "static",
        "login.page",
    }
)

# Failed logins from one address: the first few are free, then each next attempt waits
# twice as long, up to five minutes.
FREE_ATTEMPTS = 3
LONGEST_WAIT_SECONDS = 300
# A visitor's listening asks Deezer on the app's behalf: at most this many per address in
# this many seconds, so the app cannot be used to flood Deezer.
VISITOR_LISTENS = 60
VISITOR_LISTEN_SECONDS = 600
# A visitor's pages run queries on the collection: at most this many per address in this many
# seconds, far more than anyone browsing by hand opens, so nobody can keep the app busy.
VISITOR_PAGES_PER_WINDOW = 300
VISITOR_PAGE_SECONDS = 60
# Not counted: files, as a shelf alone shows a hundred covers and sending a file costs little;
# and the login, which has a limit of its own, so the owner can always log in.
_NOT_COUNTED = frozenset({"static", "covers.file", "artists.picture", "help.page", "pwa.manifest", "login.page"})


class _Window:
    """What each address did within the last so many seconds, to hold one up that does too
    much. Addresses gone quiet are forgotten, so a stream of new ones cannot fill memory."""

    def __init__(self, settings: Callable[[], tuple[int, int]]):
        # How many in how many seconds, asked on each use so a test can lower them.
        self._settings = settings
        self._times: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, address: str) -> bool:
        """Count this one, unless the address is at its limit already."""
        limit, seconds = self._settings()
        now = time.monotonic()
        with self._lock:
            if len(self._times) > 10_000:
                self._times = {a: t for a, t in self._times.items() if t and now - t[-1] <= seconds}
            recent = self._times.setdefault(address, deque())
            while recent and now - recent[0] > seconds:
                recent.popleft()
            if len(recent) >= limit:
                return False
            recent.append(now)
            return True

    def clear(self) -> None:
        with self._lock:
            self._times.clear()


_failures: dict[str, tuple[int, float]] = {}
_listens = _Window(lambda: (VISITOR_LISTENS, VISITOR_LISTEN_SECONDS))
_pages = _Window(lambda: (VISITOR_PAGES_PER_WINDOW, VISITOR_PAGE_SECONDS))
# When each address was last reported as held up, so the log names it once per window.
_reported: dict[str, float] = {}


def _password_hash() -> str | None:
    return load_settings(current_app.config["DATA_DIR"]).owner_password_hash


def _fingerprint(password_hash: str) -> str:
    # A login is tied to the password it was made with: changing it logs out other devices.
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def is_owner() -> bool:
    """Whether the one looking may change things: logged in, or no password set at all."""
    if "is_owner" not in g:
        stored = _password_hash()
        g.is_owner = not stored or session.get("owner") == _fingerprint(stored)
    return g.is_owner


def remember_owner(password_hash: str) -> None:
    """Log this device in as the owner, tied to the hash that was verified: until logging
    out, or until the password changes."""
    session.clear()
    session.permanent = True
    session["owner"] = _fingerprint(password_hash)
    g.pop("is_owner", None)


def guard():
    """Run before every request: a visitor gets only what VISITOR_PAGES lists, to read, and
    only so many pages a minute."""
    if request.endpoint is None or is_owner():
        return None
    if request.endpoint not in _NOT_COUNTED and not _pages.allow(_address()):
        return _too_busy()
    if request.method in ("GET", "HEAD"):
        if request.endpoint in VISITOR_PAGES:
            return None
        return redirect(url_for("login.page", next=request.full_path))
    # What a visitor may send: the password, and the language for the device.
    if request.endpoint in ("login.page", "language.choose"):
        return None
    abort(403)


def _too_busy() -> Response:
    address = _address()
    now = time.monotonic()
    if now - _reported.get(address, -VISITOR_PAGE_SECONDS) >= VISITOR_PAGE_SECONDS:
        _reported[address] = now
        if len(_reported) > 10_000:
            _reported.clear()
        current_app.logger.warning("Visitor held up for too many requests from %s", address)
    response = Response(_("Too many requests. Try again in a minute."), 429, mimetype="text/plain")
    response.headers["Retry-After"] = str(VISITOR_PAGE_SECONDS)
    return response


def visitor_may_listen() -> bool:
    """Whether a visitor's next listen stays within the limit; the owner always may."""
    return is_owner() or _listens.allow(_address())


def _address() -> str:
    """Who is asking, for the limits. Only the proxies the app is told to trust
    (SLEEVE_SHELF_PROXIES, see create_app) may name the address behind them; otherwise a
    client could name a new one with every request and never be held up."""
    return request.remote_addr or ""


def _wait(address: str) -> int:
    """Seconds this address still has to wait before its next attempt."""
    count, last = _failures.get(address, (0, 0.0))
    if count < FREE_ATTEMPTS:
        return 0
    wait = min(2 ** (count - FREE_ATTEMPTS + 1), LONGEST_WAIT_SECONDS)
    return max(0, int(last + wait - time.monotonic() + 0.999))


def _within(target: str | None) -> bool:
    """Whether target is a page of this app, never another site. A backslash is refused too,
    as browsers read "/\\elsewhere.example" as another site, and so is a control character,
    which browsers drop ("/\t/elsewhere.example")."""
    return bool(
        target
        and target.startswith("/")
        and not target.startswith("//")
        and "\\" not in target
        and not any(ord(char) < 32 or ord(char) == 127 for char in target)
        and not urlsplit(target).netloc
    )


def safe_next(target: str | None) -> str:
    """Where to go after logging in: a page of this app, else the start."""
    return target if _within(target) else url_for("index")


def redirect_within(target: str | None, fallback: str) -> Response:
    """Go to target when it is a page of this app, else to fallback.

    The check stands right beside the redirect — no host and no scheme — so a code scanner
    sees it guards the redirect; _within holds the rest of it.
    """
    parts = urlsplit(target or "")
    if target and _within(target) and not parts.netloc and not parts.scheme:
        return redirect(target)
    return redirect(fallback)


@blueprint.route("/login", methods=["GET", "POST"])
def page():
    if not has_password(current_app.config["DATA_DIR"]):
        return redirect(url_for("index"))
    target = safe_next(request.values.get("next"))
    error = None
    status = 200
    if request.method == "POST":
        address = _address()
        wait = _wait(address)
        if wait:
            error = _("Too many attempts. Try again in %(seconds)d seconds.", seconds=wait)
            status = 429
            current_app.logger.warning("Login refused, too many attempts, from %s", address)
        elif verified := verified_hash(current_app.config["DATA_DIR"], request.form.get("password", "")):
            _failures.pop(address, None)
            remember_owner(verified)
            current_app.logger.info("Owner logged in from %s", address)
            return redirect_within(target, url_for("index"))
        else:
            count, _last = _failures.get(address, (0, 0.0))
            _failures[address] = (count + 1, time.monotonic())
            # A tool such as fail2ban can watch for this line and block the address.
            current_app.logger.warning("Failed login from %s", address)
            error = _("That is not the password.")
            status = 401
    return render_template("login/page.html", target=target, error=error), status


@blueprint.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("browse.browse"))
