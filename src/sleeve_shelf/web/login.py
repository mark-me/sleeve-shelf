"""The owner's login, and what a visitor without one may do.

Closed unless listed: a visitor may open only the pages in VISITOR_PAGES, and only to read
them. Everything else — every change, every other screen, and any screen added later —
asks for the login. Without a password the app is open and everyone is the owner.
"""

import hashlib
import time
from collections import defaultdict, deque
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

from sleeve_shelf.access import check_password, has_password
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

_failures: dict[str, tuple[int, float]] = {}
_listens: dict[str, deque] = defaultdict(deque)


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


def remember_owner() -> None:
    """Log this device in as the owner, until logging out or the password changes."""
    session.clear()
    session.permanent = True
    session["owner"] = _fingerprint(_password_hash())
    g.pop("is_owner", None)


def guard():
    """Run before every request: a visitor gets only what VISITOR_PAGES lists, to read."""
    if request.endpoint is None or is_owner():
        return None
    if request.method in ("GET", "HEAD"):
        if request.endpoint in VISITOR_PAGES:
            return None
        return redirect(url_for("login.page", next=request.full_path))
    # The one thing a visitor may send: the password.
    if request.endpoint == "login.page":
        return None
    abort(403)


def visitor_may_listen() -> bool:
    """Whether a visitor's next listen stays within the limit; the owner always may."""
    if is_owner():
        return True
    now = time.monotonic()
    recent = _listens[_address()]
    while recent and now - recent[0] > VISITOR_LISTEN_SECONDS:
        recent.popleft()
    if len(recent) >= VISITOR_LISTENS:
        return False
    recent.append(now)
    return True


def _address() -> str:
    """Who is asking. Behind a proxy (as on the internet) the proxy adds the address it
    saw last in X-Forwarded-For; earlier entries come from the client and are not trusted."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.rsplit(",", 1)[-1].strip() or request.remote_addr or ""


def _wait(address: str) -> int:
    """Seconds this address still has to wait before its next attempt."""
    count, last = _failures.get(address, (0, 0.0))
    if count < FREE_ATTEMPTS:
        return 0
    wait = min(2 ** (count - FREE_ATTEMPTS + 1), LONGEST_WAIT_SECONDS)
    return max(0, int(last + wait - time.monotonic() + 0.999))


def _safe_next(target: str | None) -> str:
    """Where to go after logging in: a page of this app, never another site."""
    if target and target.startswith("/") and not target.startswith("//") and not urlsplit(target).netloc:
        return target
    return url_for("index")


@blueprint.route("/login", methods=["GET", "POST"])
def page():
    if not has_password(current_app.config["DATA_DIR"]):
        return redirect(url_for("index"))
    target = _safe_next(request.values.get("next"))
    error = None
    status = 200
    if request.method == "POST":
        address = _address()
        wait = _wait(address)
        if wait:
            error = _("Too many attempts. Try again in %(seconds)d seconds.", seconds=wait)
            status = 429
        elif check_password(current_app.config["DATA_DIR"], request.form.get("password", "")):
            _failures.pop(address, None)
            remember_owner()
            return redirect(target)
        else:
            count, _last = _failures.get(address, (0, 0.0))
            _failures[address] = (count + 1, time.monotonic())
            error = _("That is not the password.")
            status = 401
    return render_template("login/page.html", target=target, error=error), status


@blueprint.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("browse.browse"))
