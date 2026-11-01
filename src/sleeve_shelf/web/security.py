"""What the browser is told to allow, and refusing changes sent from other sites.

The Content-Security-Policy lets a page run only the app's own scripts, and the few inline
ones that carry this request's nonce; it lets it load images, sound and video only from
where the app takes them (Discogs, Deezer, YouTube without cookies). Should a stranger's
markup ever get into a page, the browser does not run it. Nothing may show the app in a
frame, so it cannot be overlaid to make the owner click.
"""

import secrets
from urllib.parse import urlsplit

from flask import abort, g, request

# What a page of the app may load, besides itself.
_APP_SOURCES = {
    "default-src": "'self'",
    "script-src": "'self' 'nonce-{nonce}'",
    "style-src": "'self' https://fonts.googleapis.com",
    # Bootstrap's own and the templates' style="…" attributes; they cannot run anything.
    "style-src-attr": "'unsafe-inline'",
    "font-src": "'self' https://fonts.gstatic.com",
    # Covers and pictures from Discogs and Deezer; Bootstrap draws some icons as data: images.
    "img-src": "'self' data: https://i.discogs.com https://*.discogs.com https://*.dzcdn.net",
    # Deezer's 30-second previews.
    "media-src": "https://*.dzcdn.net",
    "frame-src": "https://www.youtube-nocookie.com",
    "connect-src": "'self'",
    "manifest-src": "'self'",
    "object-src": "'none'",
    "base-uri": "'self'",
    "form-action": "'self'",
    "frame-ancestors": "'none'",
}

# The help is the documentation site, built by Zensical: it runs inline scripts of its own and
# draws its diagrams with Mermaid from a CDN. It holds nothing but our own pages.
_HELP_SOURCES = {
    "default-src": "'self'",
    "script-src": "'self' 'unsafe-inline' https://unpkg.com",
    "style-src": "'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src": "'self' data: https://fonts.gstatic.com",
    "img-src": "'self' data: https:",
    "connect-src": "'self' https://api.github.com",
    "object-src": "'none'",
    "base-uri": "'self'",
    "frame-ancestors": "'none'",
}

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}

# Methods that change nothing; any other must come from a page of the app itself.
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def csp_nonce() -> str:
    """This request's nonce: an inline script carrying it may run, any other may not.

    Returns:
        The nonce.
    """
    if "csp_nonce" not in g:
        g.csp_nonce = secrets.token_urlsafe(16)
    return g.csp_nonce


def add_headers(response):
    """Run after every request: the security headers on the answer.

    Args:
        response: The answer.

    Returns:
        The answer.
    """
    sources = _HELP_SOURCES if request.blueprint == "help" else _APP_SOURCES
    policy = "; ".join(f"{name} {value}" for name, value in sources.items())
    response.headers["Content-Security-Policy"] = policy.replace("{nonce}", csp_nonce())
    for name, value in _HEADERS.items():
        response.headers.setdefault(name, value)
    return response


def reject_other_sites():
    """Run before every request: a change has to come from a page of the app.

    Browsers say where a request comes from. Sec-Fetch-Site must then be same-origin; a browser too
    old to send it still sends Origin, which must be this host. A request with neither is no
    browser's, so no visitor can be tricked into sending it.

    Returns:
        The refusal, or None to let it through.
    """
    if request.method in _SAFE_METHODS:
        return None
    site = request.headers.get("Sec-Fetch-Site")
    if site is not None:
        if site not in ("same-origin", "none"):
            abort(403)
        return None
    origin = request.headers.get("Origin")
    if origin is not None and (origin == "null" or urlsplit(origin).netloc != request.host):
        abort(403)
    return None
