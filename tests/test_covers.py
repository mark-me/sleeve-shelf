"""Tests for covers and artist pictures kept in the data directory."""

import pytest

from sleeve_shelf import create_app
from sleeve_shelf.covers import (
    COVER_DIR,
    cover_name,
    download_images,
    image_urls,
    missing_images,
    sort_into_folders,
)
from sleeve_shelf.domain import (
    Album,
    Artist,
    ArtistClusterAssignment,
    ArtistEnrichment,
    Cabinet,
    Cluster,
    EraBand,
    Placement,
    PlacementSource,
    Shelf,
)
from sleeve_shelf.persistence import JsonStore
from datetime import datetime

THUMB = "https://i.discogs.com/hope150.jpeg"
LARGE = "https://i.discogs.com/hope600.jpeg"
GONE = "https://i.discogs.com/gone150.jpeg"
PICTURE = "https://i.discogs.com/low150.jpeg"


class _Images:
    """Stands in for Discogs' image servers; an address it does not know is gone."""

    def __init__(self):
        self.asked = []

    def image(self, url):
        self.asked.append(url)
        return None if "gone" in url else b"jpeg " + url.encode()


@pytest.fixture
def app(tmp_path):
    app = create_app(tmp_path / "data")
    store = JsonStore(tmp_path / "data")
    store.save(Cabinet, [Cabinet(1, "Kast")])
    store.save(Shelf, [Shelf(1, 1, "a", width_cm=30)])
    store.save(EraBand, [])
    store.save(Cluster, [Cluster(1, "Slowcore", 1)])
    store.save(Artist, [Artist(1, "Low", start_year=1993, discogs_artist_id=30)])
    store.save(ArtistClusterAssignment, [ArtistClusterAssignment(1, 1, confirmed=True)])
    store.save(ArtistEnrichment, [ArtistEnrichment(30, None, PICTURE, datetime(2026, 10, 11))])
    store.save(
        Album,
        [
            Album(1, 1, "I Could Live In Hope", release_id=11, cover_url=THUMB, cover_image_url=LARGE),
            Album(2, 1, "The Curtain Hits The Cast", release_id=12, cover_url=GONE),
            Album(3, 1, "Trust", release_id=13),
        ],
    )
    store.save(
        Placement,
        [Placement(1, 1, 0, PlacementSource.MANUAL), Placement(2, 1, 1, PlacementSource.MANUAL)],
    )
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _store(app):
    return JsonStore(app.config["DATA_DIR"])


def test_every_image_a_page_shows_is_listed_once(app):
    store = _store(app)

    urls = image_urls(store.load(Album), store.load(ArtistEnrichment))

    # Small covers first, then large ones, then the artists; an album without a cover has none.
    assert urls == [THUMB, GONE, LARGE, PICTURE]
    assert missing_images(store) == urls


def test_images_are_stored_once_and_one_that_is_gone_is_not_asked_for_again(app):
    store = _store(app)
    images = _Images()
    counts = []

    fetched = download_images(store, images, missing_images(store), counts.append)

    assert fetched == 3 and counts == [1, 2, 3, 4]
    directory = store.data_dir / COVER_DIR
    # Covers and pictures each go into a folder of their own.
    assert (directory / "albums" / cover_name(THUMB)).read_bytes() == b"jpeg " + THUMB.encode()
    assert (directory / "albums" / cover_name(LARGE)).exists()
    assert (directory / "artists" / cover_name(PICTURE)).exists()
    assert not (directory / "albums" / cover_name(GONE)).exists()
    assert not [path for path in directory.rglob("*") if path.suffix == ".part"]
    assert sorted(path.name for path in directory.iterdir()) == ["albums", "artists"]
    # Nothing is left to fetch, the image Discogs no longer has included.
    assert missing_images(store) == []
    download_images(store, images, missing_images(store))
    assert len(images.asked) == 4


def test_pages_show_the_stored_copy_and_discogs_for_the_rest(app, client):
    store = _store(app)
    before = client.get("/browse").text
    assert f'src="{THUMB}"' in before and "/covers/" not in before

    download_images(store, _Images(), [THUMB, LARGE, PICTURE])

    shelf = client.get("/browse").text
    assert f'src="/covers/albums/{cover_name(THUMB)}"' in shelf and THUMB not in shelf
    # The cover that could not be stored is still shown from Discogs.
    assert f'src="{GONE}"' in shelf
    album = client.get("/albums/1").text
    assert f'data-src="/covers/albums/{cover_name(LARGE)}"' in album
    layout = client.get("/layout/").text
    assert f'data-covers="/covers/albums/{cover_name(THUMB)}|{GONE}"' in layout
    assert f'src="/covers/artists/{cover_name(PICTURE)}"' in client.get("/artists/").text


def test_stored_images_are_served_from_the_data_directory(app, client):
    download_images(_store(app), _Images(), [THUMB])

    response = client.get(f"/covers/albums/{cover_name(THUMB)}")

    assert response.data == b"jpeg " + THUMB.encode()
    assert response.mimetype == "image/jpeg"
    assert "max-age=31536000" in response.headers["Cache-Control"]
    assert client.get("/covers/albums/unknown.jpg").status_code == 404
    assert client.get(f"/covers/artists/{cover_name(THUMB)}").status_code == 404
    assert client.get(f"/covers/elsewhere/{cover_name(THUMB)}").status_code == 404
    gone = cover_name(GONE).replace(".jpg", ".missing")
    assert client.get(f"/covers/albums/{gone}").status_code == 404


def test_images_from_before_the_folders_are_sorted_into_them(app, tmp_path):
    store = _store(app)
    directory = store.data_dir / COVER_DIR
    directory.mkdir()
    for name in (cover_name(THUMB), cover_name(PICTURE), cover_name(GONE).replace(".jpg", ".missing")):
        (directory / name).write_bytes(b"kept")
    # Of an album that was removed since: no album or artist points to it any more.
    (directory / "orphan.jpg").write_bytes(b"kept")

    assert sort_into_folders(store) == 3

    assert (directory / "albums" / cover_name(THUMB)).read_bytes() == b"kept"
    assert (directory / "artists" / cover_name(PICTURE)).exists()
    assert (directory / "albums" / cover_name(GONE).replace(".jpg", ".missing")).exists()
    assert (directory / "orphan.jpg").exists()
    # Nothing is fetched again for what was moved, and starting the app does the sorting too.
    assert missing_images(store) == [LARGE]
    (directory / cover_name(LARGE)).write_bytes(b"kept")
    create_app(store.data_dir)
    assert (directory / "albums" / cover_name(LARGE)).exists() and missing_images(store) == []


def test_discogs_screen_says_how_many_images_are_stored(app, client):
    page = client.get("/discogs/").text
    assert "0 of 4 images" in page
    assert "The images of 4 covers and artists still have to be stored." in page

    download_images(_store(app), _Images(), [THUMB, GONE, LARGE, PICTURE])

    page = client.get("/discogs/").text
    # The image that is gone counts as dealt with: 3 stored of the 4 the pages show.
    assert "3 of 4 images" in page
    assert "still have to be stored" not in page
    assert "1 image is no longer at Discogs and could not be stored." in page


def _image(kind, size, colour="red"):
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGBA" if kind == "PNG" else "RGB", size, colour).save(out, kind)
    return out.getvalue()


PNG = _image("PNG", (1200, 800))
JPEG = _image("JPEG", (40, 40), "blue")


def test_user_can_add_a_picture_of_an_artist_that_goes_before_discogs(app, client):
    import io

    from PIL import Image

    page = client.get("/artists/1").text
    assert "This picture comes from Discogs." in page and f'src="{PICTURE}"' in page

    client.post("/artists/1/picture", data={"picture": (io.BytesIO(PNG), "low.png")})

    artist = _store(app).load(Artist)[0]
    assert artist.picture_file.startswith("1-") and artist.picture_file.endswith(".png")
    own = f"/artists/pictures/{artist.picture_file}"
    page = client.get("/artists/1").text
    # A small copy was made at once; the list and the page show that, the pop-up the full one.
    small = own.replace(".png", ".thumb.jpg")
    assert f'src="{small}"' in page and f'data-src="{own}"' in page and PICTURE not in page
    assert "This is a picture you added" in page
    listed = client.get("/artists/").text
    assert f'src="{small}"' in listed and own not in listed
    assert client.get(own).data == PNG
    thumb = Image.open(io.BytesIO(client.get(small).data))
    assert (thumb.format, thumb.size) == ("JPEG", (300, 200))
    assert len(client.get(small).data) < len(PNG)
    # It is kept in the data directory, apart from what was downloaded from Discogs.
    assert (_store(app).data_dir / "artist_pictures" / artist.picture_file).exists()

    # Replacing it leaves one file; removing it brings the Discogs picture back.
    client.post("/artists/1/picture", data={"picture": (io.BytesIO(JPEG), "low.jpg")})
    names = sorted(p.name for p in (_store(app).data_dir / "artist_pictures").iterdir())
    assert len(names) == 2 and names[1] == names[0].replace(".jpg", ".thumb.jpg")
    client.post("/artists/1/picture/remove")
    assert _store(app).load(Artist)[0].picture_file is None
    assert not list((_store(app).data_dir / "artist_pictures").iterdir())
    assert f'src="{PICTURE}"' in client.get("/artists/1").text


def test_a_file_that_is_no_image_is_refused_as_a_picture(app, client):
    import io

    response = client.post(
        "/artists/1/picture",
        # It starts like a PNG, but there is no picture in it.
        data={"picture": (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"not an image"), "x.png")},
        follow_redirects=True,
    )

    assert "not a JPEG, PNG, GIF or WebP image" in response.text
    assert _store(app).load(Artist)[0].picture_file is None


def test_a_picture_can_be_set_from_the_command_line(app, tmp_path, monkeypatch, capsys):
    from sleeve_shelf import main

    image = tmp_path / "low.jpg"
    image.write_bytes(JPEG)
    monkeypatch.setenv("SLEEVE_SHELF_DATA_DIR", str(app.config["DATA_DIR"]))

    main(["set-picture", "low", str(image)])

    assert "Picture of Low set" in capsys.readouterr().out
    assert _store(app).load(Artist)[0].picture_file.endswith(".jpg")


def test_a_picture_from_before_gets_its_small_copy_when_first_shown(app, client):
    store = _store(app)
    directory = store.data_dir / "artist_pictures"
    directory.mkdir()
    (directory / "1-old.png").write_bytes(PNG)
    artists = store.load(Artist)
    artists[0].picture_file = "1-old.png"
    store.save(Artist, artists)

    listed = client.get("/artists/").text

    assert 'src="/artists/pictures/1-old.thumb.jpg"' in listed
    assert (directory / "1-old.thumb.jpg").exists()
