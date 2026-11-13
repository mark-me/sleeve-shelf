# Contributing to Sleeve & Shelf

Thanks for your interest in Sleeve & Shelf. It is a personal, self-hosted app for organising a vinyl collection, built around one owner's real shelves — but bug reports, ideas and pull requests are welcome.

## Before you start

- **Found a bug?** Open an issue with what you did, what you expected and what happened instead. A screenshot and the browser you used help.
- **Want a feature or a larger change?** Open an issue first to talk it through. What the app does — and deliberately does not do — is written down in [`docs/requirements.md`](docs/requirements.md), and decisions on scope rest with the maintainer, so agreeing on the idea first saves you work.
- **Small fixes** (typos, an obvious bug, documentation) can go straight to a pull request.
- **Security issues**: please do not open a public issue. Use GitHub's *Report a vulnerability* on the [Security tab](https://github.com/mark-me/sleeve-shelf/security) to report it privately.

## Setting up

You need [uv](https://docs.astral.sh/uv/). It creates the environment from `pyproject.toml` on the first run.

```sh
git clone https://github.com/mark-me/sleeve-shelf.git
cd sleeve-shelf
uv run python -m sleeve_shelf          # the app on http://127.0.0.1:5000
```

Always use the `python -m` form shown here (`uv run python -m pytest`, not `uv run pytest`): on some managed machines the generated console scripts are refused, while the module form works everywhere.

Your collection lives in a data directory (`data/` by default), which is git-ignored. When trying something on real data, point the app at a **copy**:

```sh
SLEEVE_SHELF_DATA_DIR=/tmp/data-copy SLEEVE_SHELF_PORT=5077 uv run python -m sleeve_shelf
```

Never commit a data directory or `config.yaml`: it holds a Discogs token and a password hash.

The [developer guide](https://mark-me.github.io/sleeve-shelf/developer/) explains the architecture, the data model, the sorting engine, development and deployment in more depth.

## Checks every change passes

Run these before you open a pull request; they run again when a change reaches `main` or `test`, and a pull request is scanned for vulnerable dependencies:

```sh
uv run python -m pytest                            # the tests
uv run python -m ruff check src tests              # unused and undefined names, docstrings, complexity
cd docs-site && uv run python -m zensical build --strict   # the documentation; warnings fail it
```

## How the code is organised

The code keeps a strict separation of concerns, and `tests/test_architecture.py` checks it:

- **Layers**: `domain` (plain dataclasses), `ingestion`, `sorting` (pure functions), `persistence`, `library`, then `shelving`, `fetching` and `insights` (which use nothing of each other), and `web` on top. Only `web/` knows Flask.
- **Thin views**: a view reads the form and shows a page; a service gathers what the page needs.
- **Docstrings** follow the Google style — modules, classes (fields under `Attributes:`) and public functions (`Args:`, `Returns:`, `Raises:`). The developer guide's Reference pages are generated from them.

A few things that are easy to get wrong:

- **UI text is translated.** The app is in English and Dutch. Wrap new text in `_()` or `ngettext()`, extract the messages and fill in the Dutch in `src/sleeve_shelf/translations/nl/LC_MESSAGES/messages.po` — a test fails otherwise. The commands are in the [developer guide](https://mark-me.github.io/sleeve-shelf/developer/development/).
- **The Content-Security-Policy runs no inline handlers** (`onclick="…"`) and no inline script without the page's nonce: put behaviour in a static file.
- **Visitors may only read.** A new screen is the owner's by default; a page visitors may open hides its actions from them.
- **Nothing is moved or lost silently.** A proposal sits next to the current layout until it is accepted, and a change to the shelves by hand keeps a version to go back to. New features keep to that.
- **Several files, no transactions.** Changes to several entities that belong together go inside `with store.together(...)`, so a failure halfway undoes them all.

## Tests and documentation

- **Every change comes with tests.** They live in `tests/`, use real files in `tmp_path`, and drive the web layer through Flask's test client.
- **The requirements move with the code.** A change in behaviour is reflected in [`docs/requirements.md`](docs/requirements.md) in the same pull request.
- **The user guide** (`docs-site/docs/user/`) describes what a user sees; update it when a screen changes. Every level-2 heading starts with an emoji that is unique across the site.

## Commits and pull requests

- Work on a branch, not on `main`.
- Write commit messages in **English**: a short subject line, then a body when the change needs explaining — one line per paragraph, without hard line wraps.
- In the pull request, say what changed and why, and what you checked by hand (which screens you looked at, on which device).
- Keep a pull request to one change. A refactoring and a new feature are easier to review apart.

## Using AI tools

This project itself was built with AI assistance (see [AI_DISCLOSURE.md](AI_DISCLOSURE.md)). You are welcome to use such tools too, as long as you understand, have run and stand behind what you submit.

## Licence

By contributing, you agree that your contributions are licensed under the project's [MIT License](LICENSE).
