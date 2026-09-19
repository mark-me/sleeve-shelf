# Sleeve & Shelf

Sleeve & Shelf is a self-hosted web application that organizes a vinyl record collection across physical storage (cabinets and shelves), based on musical kinship, artist era, and available shelf space.

It's built for collectors who track their collection on [Discogs](https://www.discogs.com/) and want a sorting proposal they can review and fine-tune, rather than a rigid, fully automated system.

## Status

This project is currently in the requirements/design phase — no code has been written yet. See [`docs/requirements.md`](docs/requirements.md) for the full requirements and phased roadmap.

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
