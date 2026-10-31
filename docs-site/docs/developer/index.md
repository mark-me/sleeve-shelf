# Developer guide

Sleeve & Shelf is a single-user Flask app, written in Python, that keeps its data in plain JSON files read and written through DuckDB. This guide explains how the code is laid out and why, so a change lands in the right place.

## 🛠️ What you need to know first

- **Python with [uv](https://docs.astral.sh/uv/).** Always use the module form — `uv run python -m sleeve_shelf`, `uv run python -m pytest` — not the generated console scripts; some managed machines refuse those.
- **Flask, server-rendered.** One blueprint per screen, Jinja templates, a little vanilla JavaScript. Bootstrap, SortableJS and Cytoscape.js are vendored, so the app works offline.
- **No database server.** Every entity is one JSON file in the data directory; DuckDB reads and writes them with SQL.
- **English in the code, the UI, and the requirements.** UI copy goes through Flask-Babel.

## 📜 Principles

These hold for every change:

Strict separation of concerns
:   Domain objects know nothing of storage or the web; the sorting engine is pure functions on domain objects; blueprints read a form, call a service, and render a template. See [Architecture](architecture.md).

Nothing is moved or lost silently
:   A proposal sits next to the current layout until accepted. A later workbook upload changes only the layout. A shelf can only be removed when empty. Changing the layout by hand keeps a version to go back to.

Sorting follows the real shelves
:   The sorting logic was written to match an actual collection, and checked against it. When a rule is unclear, test it against the data rather than reasoning from first principles.

Tests accompany every feature
:   They live in `tests/`, use real files in `tmp_path`, and drive the web layer through Flask's test client.

## 📚 Reference

The [Reference](reference/domain.md) pages are generated from the docstrings of the domain, the sorting engine, the store and the network; the pages around them explain how it fits together. Docstrings follow the Google style, and `uv run python -m ruff check src tests` and `tests/test_architecture.py` check them.

## 🗂️ The requirements document

`docs/requirements.md` in the repository is the source of truth for scope, sorting logic, data model, and every screen. It moves with the code: a change in behaviour is reflected there in the same piece of work, and its last section, *Open questions*, lists what is undecided.
