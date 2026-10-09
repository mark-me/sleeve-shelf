# Sleeve & Shelf

A self-hosted, single-user Flask app that organizes a vinyl collection across cabinets and shelves. It loads an existing layout from a spreadsheet, lets the owner browse and search it in physical shelf order, links the albums to Discogs, and proposes a sorted layout that can be adjusted by hand.

The owner, Mark, writes in Dutch; reply in Dutch. Code, comments, UI copy, and `docs/requirements.md` are in English.

## Where things stand

`docs/requirements.md` is the source of truth for scope, sorting logic, data model, and every screen. Read it before changing behavior. Its last section, **Open questions**, lists what is undecided and what was deliberately parked.

- **Phase 1a (load a layout, browse, search)** is built.
- **Phase 1b (Discogs, sorting proposal, management screens)** is built, including starting without a workbook.
- What remains from Phase 1 is listed under Open questions: two estimates to tune against real measurements, and one parked point from 1a (the upload and preview screens never looked at).
- **Phase 2** has started: syncing the collection through the Discogs API on demand is built, and so are album covers (hotlinked from Discogs, filled by a sync), artist pictures (hotlinked too; a sync names the artist, the enrichment fetches the picture) and the showcase (a top-loader holding a sample of an artist's albums, exchanged one for one with the shelf). A new purchase whose styles point an artist to another cluster is reported and waits for a decision (`shifts.py`). The rest of Phase 2 (a suggested spot for new purchases, rule suggestions) is not built, and neither is Phase 3.

## Commands

```sh
uv run python -m sleeve_shelf                      # run the app on http://127.0.0.1:5000
uv run python -m pytest                            # run the tests
uv run python -m sleeve_shelf load <workbook.xlsx> # load a layout workbook
uv run python -m sleeve_shelf import-discogs <collection.csv>
uv run python -m sleeve_shelf enrich               # fetch styles and original years from Discogs
```

After changing UI copy, extract the translation template again and bring the catalogues up to date (a test fails otherwise):

```sh
uv run python -m babel.messages.frontend extract -F babel.cfg --project "Sleeve & Shelf" --copyright-holder "Mark Zwart" --no-wrap --sort-by-file --add-location=file -o src/sleeve_shelf/translations/messages.pot .
uv run python -m babel.messages.frontend update -i src/sleeve_shelf/translations/messages.pot -d src/sleeve_shelf/translations --no-wrap --no-fuzzy-matching --ignore-obsolete
```

Always use the `python -m` form. On Mark's managed work laptop the generated `.exe` console scripts (`uv run pytest`, `uv run sleeve-shelf`) are refused; the module form works everywhere.

Environment variables: `SLEEVE_SHELF_DATA_DIR` (default `data`), `SLEEVE_SHELF_HOST`, `SLEEVE_SHELF_PORT`.

## Layout of the code

Strict separation of concerns; keep it that way.

| Path | What it holds |
| --- | --- |
| `src/sleeve_shelf/domain/` | Plain dataclasses, standard library only. No storage or web knowledge. |
| `src/sleeve_shelf/ingestion/` | Reading the outside world: the layout workbook, the Discogs CSV export, the Discogs API (collection, release, master and artist), the format-string parser. |
| `src/sleeve_shelf/sorting/` | The sorting engine: pure functions on domain objects (era bands, families, order, placement). |
| `src/sleeve_shelf/persistence/` | `JsonStore` (one JSON file per entity, read and written through DuckDB) and the read queries for Browse. |
| `src/sleeve_shelf/*.py` | Application services that tie the layers together: `collection`, `proposal`, `placing` (moving an album or artist by hand, and the rules that bind it), `showcase`, `shifts` (a purchase that points an artist to another cluster), `versions`, `alias_groups`, `artists`, `clusters`, `config`. |
| `src/sleeve_shelf/web/` | Flask blueprints, templates, static files. One blueprint per screen. |
| `src/sleeve_shelf/web/pwa.py`, `web/static/icons/` | The web app manifest and the icons for installing the app on a phone. No service worker, on purpose. |
| `docker/` | Dockerfile and Compose examples; `.github/workflows/docker.yml` builds and publishes the image. |

Things that are easy to get wrong:

- **Adding a field to an entity** means three places: the dataclass in `domain/`, its column list in `persistence/store.py` (`_TABLES`), and the data model in `docs/requirements.md` (the entity list and the Mermaid diagram).
- **A service module and a blueprint can share a name** (`sleeve_shelf/versions.py` and `sleeve_shelf/web/versions.py`). In web modules import names explicitly — `from sleeve_shelf.versions import save_version` — not `from sleeve_shelf import versions`, which can resolve to the blueprint.
- **`JsonStore.save` rewrites the whole file.** Load the list, change it, save the list.
- **A new id comes from `store.next_id(Entity, items)`**, never from "highest + 1": ids of removed items stay taken, because saved versions and location rules still name them.
- **Queries read several entity files at once** and fail when one doesn't exist yet. Check `store.exists(...)` or `has_collection()` first.
- **UI copy goes through Flask-Babel**: `_()` and `ngettext()` in templates and views. The catalogues are in `src/sleeve_shelf/translations/` (template `messages.pot`, English `en/`); English is the only language. Compiled `.mo` files are git-ignored and not needed while there is only English — a second language needs a compile step in the Docker build.
- **Bootstrap and SortableJS are vendored** in `web/static/vendor/` so the app works offline. Don't switch them to a CDN. Album covers are the one exception: the browser fetches them from Discogs, and every page has to work without them.

## Data

The `data/` directory is git-ignored. It holds the collection as JSON files, the Discogs cache, saved layout versions in `placements/`, and `config.yaml` — which contains the Discogs token. Never commit it, and never print the token in full; the UI shows only its last four characters.

The Discogs cache (`discogs_releases.json`, `discogs_masters.json`, `discogs_artists.json`) took hours to fetch at Discogs' rate limit. Don't delete it, and don't start an enrichment while another is running.

When trying something out on real data, work on a copy of `data/` (point `SLEEVE_SHELF_DATA_DIR` at it), not on `data/` itself. `docs/import_example.xlsx` is Mark's own layout workbook and the reference for the workbook format.

## How we work

- **Requirements move with the code.** Every change in behavior is reflected in `docs/requirements.md` in the same piece of work: the relevant section, the data model if entities changed, and the Open questions list (remove what is settled, add what is newly open).
- **Decisions are Mark's.** When the requirements leave something open, say what the options are and recommend one. Record his decision in the requirements. Choices made without asking are reported as such.
- **Sorting follows Mark's real shelves.** The sorting logic was rewritten to match his workbook, and was checked against it. When a rule is unclear, test it against `docs/import_example.xlsx` and the loaded collection rather than reasoning from first principles — that is how the workbook's 20-year rule was found to contradict its own layout and left out (see Sorting logic §2).
- **Nothing is moved or lost silently.** A proposal sits next to the current layout until accepted; a later workbook upload changes only the layout; a shelf can only be removed when empty; changing the layout by hand keeps a version to go back to. Keep new features in that spirit.
- **Tests accompany every feature.** They live in `tests/`, use real files in `tmp_path`, and drive the web layer through Flask's test client.
- **Say what was and wasn't verified.** Report which screens were actually looked at and which are covered by tests only. Screenshots can be taken with headless Chrome against a server on a spare port; interactions such as dragging have not been exercised in a real browser.
- **Mark commits himself**, on a feature branch, with short Dutch commit messages. Don't commit or push unless asked.

## Known and accepted

- Browser file uploads fail on Mark's work laptop because of a local policy. That is accepted; the `load` and `import-discogs` commands are the way around it. Don't investigate it or list it as a problem.
- Shelf widths loaded from the workbook are estimates (LP-units × base width) and come out too narrow, so shelves show as overfull until measured. That is expected, not a bug.
- The Docker image builds on GitHub from the `test` and `main` branches; there is no Docker on the work laptop.
