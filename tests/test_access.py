"""Tests for the owner's login: what a visitor may do, logging in, and the password."""

import io

import pytest
from openpyxl import Workbook

from sleeve_shelf import create_app, main
from sleeve_shelf.access import (
    MIN_PASSWORD_LENGTH,
    check_password,
    has_password,
    set_password,
)
from sleeve_shelf.web import login
from sleeve_shelf.web.help import ONLINE

PASSWORD = "a long and strong one"


def _workbook() -> io.BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Kastindeling"
    sheet.append(["Locatie", "Vak", "Cluster", "Era-band (artiest)", "Artiest", "Titel"])
    sheet.append(["Kast", "a", "Singer-Songwriter", "1970s", "Tom Waits", "Closing Time"])
    content = io.BytesIO()
    workbook.save(content)
    content.seek(0)
    return content


@pytest.fixture
def app(tmp_path, monkeypatch):
    # The test client speaks plain HTTP; the real cookie is HTTPS-only (see the test below).
    monkeypatch.setenv("SLEEVE_SHELF_HTTP_LOGIN", "1")
    login._failures.clear()
    login._listens.clear()
    app = create_app(tmp_path / "data")
    client = app.test_client()
    client.post("/setup/upload", data={"workbook": (_workbook(), "layout.xlsx")})
    client.post("/setup/confirm")
    return app


def test_without_a_password_everyone_is_the_owner(app):
    client = app.test_client()

    assert client.get("/dashboard/").status_code == 200
    assert client.get("/").headers["Location"] == "/dashboard/"
    page = client.get("/settings/").text
    assert "The app is open" in page and "Log in" not in page


def test_a_visitor_may_look_the_collection_up_and_nothing_more(app):
    set_password(app.config["DATA_DIR"], PASSWORD)
    visitor = app.test_client()

    # Looking up: the collection, an album, an artist, listening, the help.
    assert visitor.get("/").headers["Location"] == "/browse"
    for page in ("/browse", "/browse?q=closing", "/albums/1", "/artists/1"):
        assert visitor.get(page).status_code == 200, page
    # The help is the built site, or GitHub Pages where none is built — never the login.
    help_page = visitor.get("/help/")
    assert help_page.status_code == 200 or help_page.headers["Location"].startswith(ONLINE)
    # Every other screen asks for the login, and every change is refused.
    for page in ("/dashboard/", "/layout/", "/settings/", "/discogs/", "/unplaced", "/families/"):
        response = visitor.get(page)
        assert response.status_code == 302 and response.headers["Location"].startswith("/login"), page
    assert visitor.post("/albums/1/move", data={"shelf_id": ""}).status_code == 403
    assert visitor.post("/settings/password", data={"action": "remove"}).status_code == 403
    assert has_password(app.config["DATA_DIR"])

    # What a visitor sees: Browse and Help in the menu, no actions on the pages.
    browse = visitor.get("/browse").text
    menu = browse[browse.index('id="main-nav"'):browse.index("</nav>")]
    assert "<span>Collection</span>" in menu and "<span>Shelves</span>" not in menu and "Log in" in menu
    assert "/unplaced" not in browse and "ss-nav-count" not in browse
    album = visitor.get("/albums/1").text
    assert 'id="listen"' in album and "/albums/1/move" not in album and "Measured width" not in album
    artist = visitor.get("/artists/1").text
    assert "Tom Waits" in artist and 'name="start_year"' not in artist and "upload" not in artist
    assert 'href="/artists/"' not in artist


def test_the_owner_logs_in_stays_in_and_logs_out(app):
    set_password(app.config["DATA_DIR"], PASSWORD)
    owner = app.test_client()

    assert owner.post("/login", data={"password": "wrong"}).status_code == 401
    logged_in = owner.post("/login", data={"password": PASSWORD, "next": "/layout/"})
    assert logged_in.headers["Location"] == "/layout/"
    assert owner.get("/dashboard/").status_code == 200
    assert "Log out" in owner.get("/dashboard/").text
    # Only a page of this app is gone to after logging in.
    again = owner.post("/login", data={"password": PASSWORD, "next": "https://elsewhere.example/"})
    assert again.headers["Location"] == "/"

    owner.post("/logout")
    assert owner.get("/dashboard/").status_code == 302


def test_failed_logins_slow_down(app):
    set_password(app.config["DATA_DIR"], PASSWORD)
    stranger = app.test_client()

    for _ in range(login.FREE_ATTEMPTS):
        assert stranger.post("/login", data={"password": "guess"}).status_code == 401
    # From then on each attempt waits, even with the right password.
    stuck = stranger.post("/login", data={"password": PASSWORD})
    assert stuck.status_code == 429 and "Try again in" in stuck.text
    # Naming another address does not help: without trusted proxies it is not believed.
    spoofed = stranger.post("/login", data={"password": PASSWORD}, headers={"X-Forwarded-For": "203.0.113.9"})
    assert spoofed.status_code == 429


def test_changing_the_password_logs_out_other_devices(app):
    set_password(app.config["DATA_DIR"], PASSWORD)
    phone, laptop = app.test_client(), app.test_client()
    for device in (phone, laptop):
        device.post("/login", data={"password": PASSWORD})

    too_short = laptop.post("/settings/password", data={"current": PASSWORD, "new": "short", "repeat": "short"})
    assert "at least" in too_short.headers["Location"].replace("+", " ")
    laptop.post("/settings/password", data={"current": PASSWORD, "new": "another strong one", "repeat": "another strong one"})

    assert laptop.get("/dashboard/").status_code == 200
    assert phone.get("/dashboard/").status_code == 302
    assert check_password(app.config["DATA_DIR"], "another strong one")

    # Removing it opens the app again.
    laptop.post("/settings/password", data={"current": "another strong one", "action": "remove"})
    assert app.test_client().get("/dashboard/").status_code == 200


def test_a_visitor_s_listening_is_limited(app, monkeypatch):
    set_password(app.config["DATA_DIR"], PASSWORD)
    monkeypatch.setattr(login, "VISITOR_LISTENS", 2)

    class Deezer:
        def find_album(self, artist, title):
            return None

    app.config["DEEZER_CLIENT_FACTORY"] = Deezer
    visitor = app.test_client()
    assert [visitor.get("/albums/1/previews").status_code for _ in range(3)] == [200, 200, 429]
    assert visitor.get("/albums/1/previews").get_json()["busy"] is True


def test_the_session_cookie_is_https_only_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("SLEEVE_SHELF_HTTP_LOGIN", raising=False)
    app = create_app(tmp_path / "data")

    assert app.config["SESSION_COOKIE_SECURE"] is True
    # The key that signs it belongs to the installation and is kept.
    assert (tmp_path / "data" / "session_key").read_text() == create_app(tmp_path / "data").secret_key.decode()


def test_the_password_is_set_from_the_command_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SLEEVE_SHELF_DATA_DIR", str(tmp_path / "data"))
    answers = iter([PASSWORD, PASSWORD])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))

    main(["set-password"])

    assert check_password(tmp_path / "data", PASSWORD)
    assert len(PASSWORD) >= MIN_PASSWORD_LENGTH
    main(["set-password", "--remove"])
    assert not has_password(tmp_path / "data")


def test_behind_a_trusted_proxy_each_visitor_has_their_own_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEVE_SHELF_HTTP_LOGIN", "1")
    monkeypatch.setenv("SLEEVE_SHELF_PROXIES", "1")
    login._failures.clear()
    app = create_app(tmp_path / "data")
    set_password(app.config["DATA_DIR"], PASSWORD)
    client = app.test_client()

    # The proxy adds the address it saw last; what the client wrote before that is not used.
    stranger = {"X-Forwarded-For": "198.51.100.7, 203.0.113.66"}
    for _ in range(login.FREE_ATTEMPTS):
        client.post("/login", data={"password": "guess"}, headers=stranger)
    assert client.post("/login", data={"password": PASSWORD}, headers=stranger).status_code == 429
    owner = client.post("/login", data={"password": PASSWORD}, headers={"X-Forwarded-For": "203.0.113.9"})
    assert owner.status_code == 302


def test_after_logging_in_only_a_page_of_this_app_is_gone_to(app):
    set_password(app.config["DATA_DIR"], PASSWORD)
    for target in ("https://elsewhere.example/", "//elsewhere.example", "/\\elsewhere.example", "/\telsewhere"):
        response = app.test_client().post("/login", data={"password": PASSWORD, "next": target})
        assert response.headers["Location"] == "/", target
    kept = app.test_client().post("/login", data={"password": PASSWORD, "next": "/layout/?room=Zolder"})
    assert kept.headers["Location"] == "/layout/?room=Zolder"


def test_a_login_is_tied_to_the_password_it_was_checked_against(app):
    from flask import session

    from sleeve_shelf.access import verified_hash

    data_dir = app.config["DATA_DIR"]
    set_password(data_dir, PASSWORD)
    # The old password is checked, then changed by another request before the login ends.
    old = verified_hash(data_dir, PASSWORD)
    set_password(data_dir, "a newer strong one")
    with app.test_request_context("/"):
        login.remember_owner(old)
        assert session["owner"]
        login.g.pop("is_owner", None)
        assert not login.is_owner()


def test_a_session_key_cut_short_is_made_anew(tmp_path):
    from sleeve_shelf.access import SESSION_KEY_FILE, session_key

    path = tmp_path / SESSION_KEY_FILE
    path.write_text("ab12")
    key = session_key(tmp_path)

    assert len(key) == 64 and path.read_text() == key.decode()
    assert path.stat().st_mode & 0o777 == 0o600
    assert session_key(tmp_path) == key
