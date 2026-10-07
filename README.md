<p align="center">
  <img src="assets/banner.png" alt="Sleeve & Shelf" width="100%">
</p>

# Sleeve & Shelf

Sleeve & Shelf is a self-hosted web application that organizes a vinyl record collection across physical storage (cabinets and shelves), based on musical kinship, artist era, and available shelf space.

It's built for collectors who track their collection on [Discogs](https://www.discogs.com/) and want a sorting proposal they can review and fine-tune, rather than a rigid, fully automated system.

## Status

Phase 1a is in progress: you can load a worked-out cabinet layout from an Excel workbook and browse or search it in physical shelf order. Generating a layout (Phase 1b) is not built yet. See [`docs/requirements.md`](docs/requirements.md) for the full requirements and phased roadmap.

## Running it

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv run python -m sleeve_shelf
```

Then open <http://127.0.0.1:5000> and upload your workbook (see `docs/import_example.xlsx` for the expected shape).

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `SLEEVE_SHELF_DATA_DIR` | `data` | Where the collection is stored as JSON files |
| `SLEEVE_SHELF_HOST` | `127.0.0.1` | Set to `0.0.0.0` to reach the app from a phone on the same network |
| `SLEEVE_SHELF_PORT` | `5000` | Port to listen on |

If your browser can't upload the file (some managed machines block uploads), load it from the command line instead — the running app picks it up straight away:

```sh
uv run python -m sleeve_shelf load path/to/layout.xlsx
```

Run the tests with `uv run python -m pytest`.

## Planned tech stack

- **Backend**: Python, Flask
- **Frontend**: Bootstrap, vanilla JavaScript (drag-and-drop via a small library such as SortableJS)
- **Storage**: flat JSON/CSV files (no database) — single-user, self-hosted
- **Deployment**: Docker

## Roadmap (summary)

- **Phase 1 — MVP**: import a Discogs CSV export, configure storage (cabinets/shelves), generate a sorting proposal (style clustering + era bands), and adjust it manually
- **Phase 2 — Ongoing use**: live Discogs API integration, album cover art, adding new purchases, showcase rotation for easily-accessible shelves
- **Phase 3 — Refinement**: deeper musical-kinship logic, search/filtering, other media formats

Full details, data model, and UI design are in [`docs/requirements.md`](docs/requirements.md).

## License

Sleeve & Shelf is licensed under the [MIT License](LICENSE).
