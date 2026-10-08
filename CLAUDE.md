# Sleeve & Shelf

A self-hosted, single-user Flask app that organizes a vinyl collection across cabinets and shelves. It loads an existing layout from a spreadsheet, lets the owner browse and search it in physical shelf order, links the albums to Discogs, and proposes a sorted layout that can be adjusted by hand.

The owner, Mark, writes in Dutch; reply in Dutch. Code, comments, UI copy, and `docs/requirements.md` are in English.

## Where things stand

`docs/requirements.md` is the source of truth for scope, sorting logic, data model, and every screen. Read it before changing behavior. Its last section, **Open questions**, lists what is undecided and what was deliberately parked.

- **Phase 1a (load a layout, browse, search)** is built.
- **Phase 1b (Discogs, sorting proposal, management screens)** is built except for the items under Open questions.
- Phase 2 and 3 are not started.

## Commands

```sh
uv run python -m sleeve_shelf                      # run the app on http://127.0.0.1:5000
uv run python -m pytest                            # run the tests
uv run python -m sleeve_shelf load <workbook.xlsx> # load a layout workbook
uv run python -m sleeve_shelf import-discogs <collection.csv>
uv run python -m sleeve_shelf enrich               # fetch styles and original years from Discogs
```

Always use the `python -m` form. On Mark's managed work laptop the generated `.exe` console scripts (`uv run pytest`, `uv run sleeve-shelf`) are refused; the module form works everywhere.

Environment variables: `SLEEVE_SHELF_DATA_DIR` (default `data`), `SLEEVE_SHELF_HOST`, `SLEEVE_SHELF_PORT`.

## Layout of the code

Strict separation of concerns; keep it that way.

| Path | What it holds |
| --- | --- |
| `src/sleeve_shelf/domain/` | Plain dataclasses, standard library only. No storage or web knowledge. |
| `src/sleeve_shelf/ingestion/` | Reading the outside world: the layout workbook, the Discogs CSV export, the Discogs API, the format-string parser. |
| `src/sleeve_shelf/sorting/` | The sorting engine: pure functions on domain objects (era bands, families, order, placement). |
| `src/sleeve_shelf/persistence/` | `JsonStore` (one JSON file per entity, read and written through DuckDB) and the read queries for Browse. |
| `src/sleeve_shelf/*.py` | Application services that tie the layers together: `collection`, `proposal`, `versions`, `alias_groups`, `artists`, `clusters`, `config`. |
| `src/sleeve_shelf/web/` | Flask blueprints, templates, static files. One blueprint per screen. |
| `docker/` | Dockerfile and Compose examples; `.github/workflows/docker.yml` builds and publishes the image. |

Things that are easy to get wrong:

- **Adding a field to an entity** means three places: the dataclass in `domain/`, its column list in `persistence/store.py` (`_TABLES`), and the data model in `docs/requirements.md` (the entity list and the Mermaid diagram).
- **A service module and a blueprint can share a name** (`sleeve_shelf/versions.py` and `sleeve_shelf/web/versions.py`). In web modules import names explicitly — `from sleeve_shelf.versions import save_version` — not `from sleeve_shelf import versions`, which can resolve to the blueprint.
- **`JsonStore.save` rewrites the whole file.** Load the list, change it, save the list.
- **Queries read several entity files at once** and fail when one doesn't exist yet. Check `store.exists(...)` or `has_collection()` first.
- **UI copy goes through Flask-Babel**: `_()` and `ngettext()` in templates and views. No translation catalogue exists yet; English is the only language.
- **Bootstrap and SortableJS are vendored** in `web/static/vendor/` so the app works offline. Don't switch them to a CDN.

## Data

The `data/` directory is git-ignored. It holds the collection as JSON files, the Discogs cache, saved layout versions in `placements/`, and `config.yaml` — which contains the Discogs token. Never commit it, and never print the token in full; the UI shows only its last four characters.

The Discogs cache (`discogs_releases.json`, `discogs_masters.json`) took hours to fetch at Discogs' rate limit. Don't delete it, and don't start an enrichment while another is running.

When trying something out on real data, work on a copy of `data/` (point `SLEEVE_SHELF_DATA_DIR` at it), not on `data/` itself. `docs/import_example.xlsx` is Mark's own layout workbook and the reference for the workbook format.

## How we work

- **Requirements move with the code.** Every change in behavior is reflected in `docs/requirements.md` in the same piece of work: the relevant section, the data model if entities changed, and the Open questions list (remove what is settled, add what is newly open).
- **Decisions are Mark's.** When the requirements leave something open, say what the options are and recommend one. Record his decision in the requirements. Choices made without asking are reported as such.
- **Sorting follows Mark's real shelves.** The sorting logic was rewritten to match his workbook, and was checked against it. When a rule is unclear, test it against `docs/import_example.xlsx` rather than reasoning from first principles.
- **Nothing is moved or lost silently.** A proposal sits next to the current layout until accepted; a later workbook upload changes only the layout; a shelf can only be removed when empty; changing the layout by hand keeps a version to go back to. Keep new features in that spirit.
- **Tests accompany every feature.** They live in `tests/`, use real files in `tmp_path`, and drive the web layer through Flask's test client.
- **Say what was and wasn't verified.** Report which screens were actually looked at and which are covered by tests only. Screenshots can be taken with headless Chrome against a server on a spare port; interactions such as dragging have not been exercised in a real browser.
- **Mark commits himself**, on a feature branch, with short Dutch commit messages. Don't commit or push unless asked.

## Known and accepted

- Browser file uploads fail on Mark's work laptop because of a local policy. That is accepted; the `load` and `import-discogs` commands are the way around it. Don't investigate it or list it as a problem.
- Shelf widths loaded from the workbook are estimates (LP-units × base width) and come out too narrow, so shelves show as overfull until measured. That is expected, not a bug.
- The Docker image builds on GitHub from the `test` and `main` branches; there is no Docker on the work laptop.
