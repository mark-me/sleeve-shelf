# Sleeve & Shelf

A self-hosted, single-user Flask app that organizes a vinyl collection across cabinets and shelves. It loads an existing layout from a spreadsheet, lets the owner browse and search it in physical shelf order, links the albums to Discogs, and proposes a sorted layout that can be adjusted by hand.

The owner, Mark, writes in Dutch; reply in Dutch. Code, comments, UI copy, and `docs/requirements.md` are in English.

## Where things stand

`docs/requirements.md` is the source of truth for scope, sorting logic, data model, and every screen. Read it before changing behavior. Its last section, **Open questions**, lists what is undecided and what was deliberately parked.

- **Phase 1a (load a layout, browse, search)** is built.
- **Phase 1b (Discogs, sorting proposal, management screens)** is built, including starting without a workbook.
- What remains from Phase 1 is listed under Open questions: two estimates to tune against real measurements, and one parked point from 1a (the upload and preview screens never looked at).
- **Phase 2** has started: syncing the collection through the Discogs API on demand is built, and so are album covers (hotlinked from Discogs, filled by a sync), artist pictures (hotlinked too; a sync names the artist, the enrichment fetches the picture) and the showcase (a top-loader holding a sample of an artist's albums, exchanged one for one with the shelf). A new purchase whose styles point an artist to another cluster is reported and waits for a decision (`shifts.py`). Artist families are suggested from the names and from the members, groups and aliases Discogs lists (`sorting/families.py`). The same connections propose a cluster for an artist without a confirmed one, before its styles do (`sorting/connections.py`). Location rules are suggested from the layout as it stands (`rule_suggestions.py`), and covers and pictures are stored in `data/covers/albums/` and `data/covers/artists/` by the fetch run (`covers.py`). An LP that stands on no shelf yet is suggested a spot in the layout as it stands (`spots.py`, `sorting/spots.py`). That completes Phase 2; Phase 3 is not started.

## Commands

```sh
uv run python -m sleeve_shelf                      # run the app on http://127.0.0.1:5000
uv run python -m pytest                            # run the tests
uv run python -m sleeve_shelf load <workbook.xlsx> # load a layout workbook
uv run python -m sleeve_shelf import-discogs <collection.csv>
uv run python -m sleeve_shelf enrich               # fetch styles and original years from Discogs
uv run python -m sleeve_shelf set-picture "<artist>" <image>  # add your own picture of an artist
uv run python -m sleeve_shelf set-password         # the owner's password (also to recover it); --remove opens the app
```

After changing UI copy, extract the translation template again and bring the catalogues up to date (a test fails otherwise):

```sh
uv run python -m babel.messages.frontend extract -F babel.cfg --project "Sleeve & Shelf" --copyright-holder "Mark Zwart" --no-wrap --sort-by-file --add-location=file -o src/sleeve_shelf/translations/messages.pot .
uv run python -m babel.messages.frontend update -i src/sleeve_shelf/translations/messages.pot -d src/sleeve_shelf/translations --no-wrap --no-fuzzy-matching --ignore-obsolete
```

The documentation site (Zensical, in `docs-site/`) has a user guide and a developer guide:

```sh
cd docs-site && uv run python -m zensical serve           # preview while writing
cd docs-site && uv run python -m zensical build --strict  # build; warnings fail it
```

Every level-2 heading there starts with an emoji, unique across the site, and the data-model diagram is copied from `docs/requirements.md`; `tests/test_docs.py` checks both, and that the navigation in `zensical.toml` names every page. Mermaid's ER diagrams treat some words as keywords (`Style`): quote such an entity name, as the requirements do. A push to `main` touching the docs publishes them to GitHub Pages (`.github/workflows/docs.yml`). The app serves the same site as its help under `/help/` (`web/help.py`): the Docker image builds and carries it (`SLEEVE_SHELF_HELP_DIR`); a local run uses `docs-site/site` once built, else GitHub Pages. Each tab in `web/navigation.py` names its part of the user guide (`help="user/shelves/#layout"`); `tests/test_help.py` checks every such page and anchor exists, so renaming a heading in the guide means updating it there.

Always use the `python -m` form. On Mark's managed work laptop the generated `.exe` console scripts (`uv run pytest`, `uv run sleeve-shelf`) are refused; the module form works everywhere.

Environment variables: `SLEEVE_SHELF_DATA_DIR` (default `data`), `SLEEVE_SHELF_HOST`, `SLEEVE_SHELF_PORT`, `SLEEVE_SHELF_HTTP_LOGIN=1` to let the owner log in over plain HTTP when trying things locally (the session cookie is HTTPS-only otherwise), and `SLEEVE_SHELF_PROXIES` — the number of proxies before the app that may say who a visitor is (1 behind Tailscale Funnel; without it a forwarded address is ignored, so all visitors behind a proxy would share one limit).

## Layout of the code

Strict separation of concerns; keep it that way.

| Path | What it holds |
| --- | --- |
| `src/sleeve_shelf/domain/` | Plain dataclasses, standard library only. No storage or web knowledge. |
| `src/sleeve_shelf/ingestion/` | Reading the outside world: the layout workbook, the Discogs CSV export, the Discogs API (collection, release, master and artist), the format-string parser. |
| `src/sleeve_shelf/sorting/` | The sorting engine: pure functions on domain objects (era bands, families, order, placement). |
| `src/sleeve_shelf/persistence/` | `JsonStore` (one JSON file per entity, read and written through DuckDB) and the read queries for Browse. |
| `src/sleeve_shelf/*.py` | Application services that tie the layers together: `collection` (loading a layout, or starting empty), `discogs_import` (a sync or an uploaded export, matches, albums that left Discogs), `enrichment` (fetching from Discogs and applying it), `proposal`, `taking_part` (which albums are sorted and which shelves a proposal fills), `placing` (moving albums by hand — from an album or artist page, or by dragging on Layout — with the check that nothing drops off a shelf, and setting the location rules and finding the ones that bind an album or artist), `showcase`, `shifts` (a purchase that points an artist to another cluster), `rule_suggestions`, `spots` (a suggested spot for a new purchase), `storage` (cabinets and shelves: adding, changing, ordering, and removing only what is empty), `widths` (album widths, estimated or measured), `covers` (images kept in the data directory), `versions`, `alias_groups`, `artists`, `clusters`, `config`. |
| `src/sleeve_shelf/web/` | Flask blueprints, templates, static files. One blueprint per screen. The menu's five sections and their tabs are declared in `web/navigation.py`; a new screen gets its tab there. |
| `src/sleeve_shelf/web/pwa.py`, `web/static/icons/` | The web app manifest and the icons for installing the app on a phone. No service worker, on purpose. |
| `docker/` | Dockerfile and Compose examples; `.github/workflows/docker.yml` builds and publishes the image, after `.github/workflows/security.yml` has checked the runtime packages (`uv export --no-dev`) for HIGH and CRITICAL vulnerabilities with a fix. Trivy runs in an empty folder so no `.trivyignore` or `trivy.yaml` from a pull request is read; keep it that way. |

Things that are easy to get wrong:

- **Adding a field to an entity** means three places: the dataclass in `domain/`, its column list in `persistence/store.py` (`_TABLES`), and the data model in `docs/requirements.md` (the entity list and the Mermaid diagram).
- **A service module and a blueprint can share a name** (`sleeve_shelf/versions.py` and `sleeve_shelf/web/versions.py`, `storage.py` likewise). In web modules import names explicitly — `from sleeve_shelf.versions import save_version` — not `from sleeve_shelf import versions`, which can resolve to the blueprint.
- **`JsonStore.save` rewrites the whole file.** Load the list, change it, save the list.
- **A new id comes from `store.next_id(Entity, items)`**, never from "highest + 1": ids of removed items stay taken, because saved versions and location rules still name them.
- **Queries read several entity files at once** and fail when one doesn't exist yet. Check `store.exists(...)` or `has_collection()` first.
- **Visitors and the owner** (`web/login.py`): with a password set, a visitor may open only the endpoints in `VISITOR_PAGES`, and only with GET; everything else asks for the login. A new screen is therefore the owner's by default. A page a visitor may open hides its actions behind `{% if is_owner %}` — check what a visitor sees when adding a button to Browse, an album's or an artist's page. Without a password everyone is the owner, so the tests that don't set one are unaffected.
- **The Content-Security-Policy** (`web/security.py`) runs no inline handler (`onchange="…"`) and no inline script without the request's nonce: give a `<script>` in a template `nonce="{{ csp_nonce() }}"`, and put behaviour in a static file. A new outside source — an image host, an audio CDN — has to be added to the policy, or the browser refuses it without a word. A page compared whole in a test differs in its nonce on every request.
- **A screen that needs a collection** is listed in `NEEDS_COLLECTION` in `src/sleeve_shelf/__init__.py`; without a collection it then leads to the wizard. Don't add a guard of its own to the blueprint.
- **UI copy goes through Flask-Babel**: `_()` and `ngettext()` in templates and views. The catalogues are in `src/sleeve_shelf/translations/` (template `messages.pot`, English `en/`); English is the only language. Compiled `.mo` files are git-ignored and not needed while there is only English — a second language needs a compile step in the Docker build.
- **Bootstrap, SortableJS and the menu icons are vendored** in `web/static/vendor/` so the app works offline. The icons are five Bootstrap Icons in one sprite, `menu-icons.svg`, each named after its section's key in `web/navigation.py`. Don't switch them to a CDN. Covers and pictures are shown from `data/covers/albums/` and `data/covers/artists/` once the fetch run has stored them (template filter `local_cover`), and from Discogs until then; every page has to work without them.

## Data

The `data/` directory is git-ignored. It holds the collection as JSON files, the Discogs cache, saved layout versions in `placements/`, stored covers and pictures in `covers/albums/` and `covers/artists/`, pictures of artists Mark added himself in `artist_pictures/` (his own: never delete or overwrite them; the `.thumb.jpg` files next to them are small copies made with Pillow), `session_key` (signs the owner's login; made once), and `config.yaml` — which contains the Discogs token and the owner's password, hashed. Never commit it, and never print the token in full; the UI shows only its last four characters.

The Discogs cache (`discogs_releases.json`, `discogs_masters.json`, `discogs_artists.json`) took hours to fetch at Discogs' rate limit. Don't delete it, and don't start an enrichment while another is running.

When trying something out on real data, work on a copy of `data/` (point `SLEEVE_SHELF_DATA_DIR` at it), not on `data/` itself. `docs/import_example.xlsx` is Mark's own layout workbook and the reference for the workbook format.

## How we work

- **Requirements move with the code.** Every change in behavior is reflected in `docs/requirements.md` in the same piece of work: the relevant section, the data model if entities changed, and the Open questions list (remove what is settled, add what is newly open).
- **Decisions are Mark's.** When the requirements leave something open, say what the options are and recommend one. Record his decision in the requirements. Choices made without asking are reported as such.
- **Sorting follows Mark's real shelves.** The sorting logic was rewritten to match his workbook, and was checked against it. When a rule is unclear, test it against `docs/import_example.xlsx` and the loaded collection rather than reasoning from first principles — that is how the workbook's 20-year rule was found to contradict its own layout and left out (see Sorting logic §2).
- **Nothing is moved or lost silently.** A proposal sits next to the current layout until accepted; a later workbook upload changes only the layout; a shelf can only be removed when empty; changing the layout by hand keeps a version to go back to. Keep new features in that spirit.
- **Tests accompany every feature.** They live in `tests/`, use real files in `tmp_path`, and drive the web layer through Flask's test client.
- **Say what was and wasn't verified.** Report which screens were actually looked at and which are covered by tests only. Screenshots can be taken with headless Chrome against a server on a spare port; interactions such as dragging have not been exercised in a real browser.
- **Mark commits himself**, on a feature branch. Commit messages are always in **English** (decided 2026-10-16), even though the conversation is in Dutch: a short subject line, and a body when the change needs explaining. Don't commit or push unless asked.

## Known and accepted

- Browser file uploads fail on Mark's work laptop because of a local policy. That is accepted; the `load` and `import-discogs` commands are the way around it. Don't investigate it or list it as a problem.
- Shelf widths loaded from the workbook are estimates (LP-units × base width) and come out too narrow, so shelves show as overfull until measured. That is expected, not a bug.
- The Docker image builds on GitHub from the `test` and `main` branches; there is no Docker on the work laptop.
