# Development

## 🧑‍💻 Setting up

```sh
git clone https://github.com/mark-me/sleeve-shelf.git
cd sleeve-shelf
uv run python -m sleeve_shelf          # the app on http://127.0.0.1:5000
```

`uv` creates the environment from `pyproject.toml` on the first run. When trying something on real data, point the app at a **copy** of your data directory:

```sh
SLEEVE_SHELF_DATA_DIR=/tmp/data-copy SLEEVE_SHELF_PORT=5077 uv run python -m sleeve_shelf
```

The command line has a few more commands:

```sh
uv run python -m sleeve_shelf load <workbook.xlsx>
uv run python -m sleeve_shelf import-discogs <collection.csv>
uv run python -m sleeve_shelf enrich
uv run python -m sleeve_shelf set-picture "<artist>" <image>
```

!!! note "Templates are read at start-up"
    The running app does not pick up changed templates. Restart it after editing one — a frequent cause of "my change doesn't show".

## 🧪 Tests

```sh
uv run python -m pytest
```

The tests live in `tests/`. They use real files in `tmp_path` rather than mocks, and drive the web layer through Flask's test client. Each service has its own test file next to the web tests: `test_placing.py`, `test_storage.py`, `test_widths.py`, `test_taking_part.py`, and so on. A feature comes with its tests.

## 🌐 Translations

All UI copy goes through Flask-Babel: `_()` and `ngettext()` in templates and views. After changing copy, extract the template again and update the catalogue — a test fails otherwise:

```sh
uv run python -m babel.messages.frontend extract -F babel.cfg --project "Sleeve & Shelf" \
  --copyright-holder "Mark Zwart" --no-wrap --sort-by-file --add-location=file \
  -o src/sleeve_shelf/translations/messages.pot .
uv run python -m babel.messages.frontend update -i src/sleeve_shelf/translations/messages.pot \
  -d src/sleeve_shelf/translations --no-wrap --no-fuzzy-matching --ignore-obsolete
```

English is the only language. A label defined in Python outside a request (such as the menu in `web/navigation.py`) uses `lazy_gettext`, imported as `_` so the extractor finds it.

## 🧹 Code style

Imports are sorted and unused names removed as ruff's `I` and `F` rules expect:

```sh
uv run --with ruff ruff check --select I,F src tests
```

Write code that reads like the code around it: plain names, short docstrings that say what something is for, comments only where the *why* is not obvious.

## 📖 This documentation

The site is built with [Zensical](https://zensical.org/) from `docs-site/`. Preview it while writing:

```sh
cd docs-site
uv run python -m zensical serve
```

and build it with `uv run python -m zensical build --strict`. Two conventions, checked by `tests/test_docs.py`:

- every level-2 heading starts with an emoji, and no emoji is used twice across the site;
- the data-model diagram is the same as the one in `docs/requirements.md`.

Diagrams are written as Mermaid in a fenced block marked `mermaid`.
