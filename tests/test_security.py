"""Tests for what the browser is told to allow, and for refusing changes from other sites."""

import re

import pytest

from sleeve_shelf import create_app


@pytest.fixture
def client(tmp_path):
    return create_app(tmp_path / "data").test_client()


def _directives(response) -> dict[str, list[str]]:
    """The policy, directive by directive, each with the sources it allows."""
    policy = response.headers["Content-Security-Policy"]
    parts = (part.split() for part in policy.split(";") if part.strip())
    return {name: sources for name, *sources in parts}


def test_every_page_says_what_it_may_load_and_that_it_may_not_be_framed(client):
    response = client.get("/setup/")
    policy = _directives(response)

    script = policy["script-src"]
    assert script[0] == "'self'" and script[1].startswith("'nonce-") and len(script) == 2
    assert policy["frame-ancestors"] == ["'none'"] and policy["object-src"] == ["'none'"]
    assert policy["media-src"] == ["https://*.dzcdn.net"]
    assert policy["frame-src"] == ["https://www.youtube-nocookie.com"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "same-origin"


def test_an_inline_script_carries_this_request_s_nonce_and_no_handler_is_inline(client):
    client.post("/setup/start")
    first, second = client.get("/rules/"), client.get("/rules/")

    nonce = re.search(r"'nonce-([^']+)'", first.headers["Content-Security-Policy"]).group(1)
    assert f'<script nonce="{nonce}">' in first.text
    assert nonce not in second.text
    for page in ("/browse", "/layout/", "/rules/", "/discogs/"):
        assert not re.search(r"\son[a-z]+=\"", client.get(page).text), page


def test_the_help_may_run_the_documentation_site_s_own_scripts(client):
    policy = _directives(client.get("/help/"))
    # Mermaid comes from unpkg; nothing else from outside may run.
    assert policy["script-src"] == ["'self'", "'unsafe-inline'", "https://unpkg.com"]
    assert policy["frame-ancestors"] == ["'none'"]


def test_a_change_from_another_site_is_refused(client):
    client.post("/setup/start")

    for headers in (
        {"Sec-Fetch-Site": "cross-site"},
        # Another app on the same domain, such as another machine of a tailnet.
        {"Sec-Fetch-Site": "same-site"},
        # A browser that sends no Sec-Fetch-Site still sends where the form came from.
        {"Origin": "https://elsewhere.example"},
        {"Origin": "null"},
    ):
        assert client.post("/storage/cabinets/new", data={"name": "Kast"}, headers=headers).status_code == 403, headers

    # From a page of the app, or from no browser at all, it goes through.
    assert client.post("/storage/cabinets/new", data={"name": "Kast"}, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 302
    assert client.post("/storage/cabinets/new", data={"name": "Koffer"}, headers={"Origin": "http://localhost"}).status_code == 302
    assert client.post("/storage/cabinets/new", data={"name": "Kist"}).status_code == 302


def test_the_settings_are_readable_by_the_app_s_own_user_only(tmp_path):
    import os

    from sleeve_shelf.config import CONFIG_FILE, Settings, load_settings, save_settings

    save_settings(tmp_path, Settings(discogs_token="secret"))
    path = tmp_path / CONFIG_FILE
    assert path.stat().st_mode & 0o777 == 0o600 and load_settings(tmp_path).discogs_token == "secret"

    # One written before, readable by others, is put right when the app starts.
    os.chmod(path, 0o644)
    create_app(tmp_path)
    assert path.stat().st_mode & 0o777 == 0o600
