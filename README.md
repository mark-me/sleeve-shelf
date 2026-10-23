<p align="center">
  <img src="assets/banner.png" alt="Sleeve & Shelf" width="100%">
</p>

# Sleeve & Shelf

*Digital housekeeping for an analog obsession.*

Sleeve & Shelf is a self-hosted web application that organizes a vinyl record collection across physical storage (cabinets and shelves), based on musical kinship, artist era, and available shelf space.

It's built for collectors who track their collection on [Discogs](https://www.discogs.com/) and want a sorting proposal they can review and fine-tune, rather than a rigid, fully automated system.

## Documentation

The documentation lives at **<https://mark-me.github.io/sleeve-shelf/>**:

- [User guide](https://mark-me.github.io/sleeve-shelf/user/) — getting started, browsing your shelves, Discogs, and how the sorting works
- [Developer guide](https://mark-me.github.io/sleeve-shelf/developer/) — architecture, data model, the sorting engine, development and deployment

## Status

Phase 1 (the MVP) and Phase 2 (ongoing use) are built.

- **Load and browse**: load a worked-out cabinet layout from an Excel workbook — or start without one — and browse or search the collection in physical shelf order, with album covers. Search also finds songs, once the tracklists are fetched from Discogs. Covers and artist pictures are stored with your data, so they also show offline.
- **Discogs**: sync the collection straight from Discogs (or upload an export), and fetch styles, original release years and artist pictures. Albums that left your Discogs collection are reported; you keep or remove them yourself.
- **Organise and sort**: manage cabinets, shelves, clusters, artist families and location rules (the app suggests families from the artist names and from Discogs' members and aliases, and rules from the layout you already have), generate a sorting proposal, adjust it by dragging, and keep versions of the layout to go back to.
- **Move**: one screen moves an album, an artist, a family or a whole cluster — to the front or the end of a shelf, or to where it belongs next to what it goes with — and shows which shelves change before anything moves.
- **New purchases**: an LP that stands on no shelf yet is suggested a spot in the layout as it is, and put there when you say so. When a purchase makes an artist's Discogs styles point to another cluster, the app says so and waits for you to move the artist or keep it where it is.
- **Showcase**: top-loaders that hold a sample of an artist's albums, exchanged one for one with the shelf.
- **On your phone**: the app can be installed to the home screen (over HTTPS) and opens on Browse / Search.
- **Visitors**: with an owner's password set, anyone else can search, browse and listen, but only the owner, logged in, can change anything (`uv run python -m sleeve_shelf set-password`).

Phase 3 has started: song search, a Dutch translation and the Move screen are built. Reorganising a table full at a time has begun: a proposal now keeps albums on the shelf they stand on where it can and leaves room on every shelf; a plan that carries it out in rounds without taking more records out than fit on your table is next (described, not built). See [`docs/requirements.md`](docs/requirements.md) for the full requirements and phased roadmap.

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
| `SLEEVE_SHELF_HTTP_LOGIN` | — | Set to `1` to let the owner log in over plain HTTP (the login cookie is HTTPS-only otherwise) |
| `SLEEVE_SHELF_PROXIES` | — | Behind Tailscale Funnel or a reverse proxy: `1`, so each visitor is told apart by their own address |

If your browser can't upload the file (some managed machines block uploads), load it from the command line instead — the running app picks it up straight away:

```sh
uv run python -m sleeve_shelf load path/to/layout.xlsx
```

### Linking the collection to Discogs

Use the **Discogs** screen in the app: set your personal access token and press **Sync**. One round fetches your collection, takes it over, and fetches styles, years, tracklists, pictures and covers; what needs your decision is listed afterwards. You can also import your collection export instead. The same can be done from the command line — put the token in `config.yaml` inside the data directory (`discogs_token: ...`; the file is git-ignored), then:

```sh
uv run python -m sleeve_shelf import-discogs path/to/discogs-collection.csv
uv run python -m sleeve_shelf enrich
```

The first links the loaded albums to the releases in your Discogs export and adds vinyl that is new. The second fetches styles and original release years; it takes roughly a second and a half per lookup, and can be stopped and restarted without fetching anything twice.

### With Docker

```sh
docker run -d --name sleeve-shelf -p 5000:5000 -v sleeve-shelf-data:/data ghcr.io/mark-me/sleeve-shelf:latest
```

The collection is kept in the `/data` volume. Use the `:test` tag for the test branch, or a version such as `:1.0.0` for a specific release.

Two Compose examples are in [`docker/`](docker/): [`docker-compose.yml`](docker/docker-compose.yml) runs a pinned release on port 5000, and [`docker-compose.test.yml`](docker/docker-compose.test.yml) runs the latest build of the `test` branch on port 5001 with its own data volume, so a production and a test container can run side by side on one machine. To load a workbook from the command line inside the container:

```sh
docker cp layout.xlsx sleeve-shelf:/tmp/layout.xlsx
docker exec sleeve-shelf python -m sleeve_shelf load /tmp/layout.xlsx
```

Run the tests with `uv run python -m pytest`.

## Tech stack

- **Backend**: Python, Flask (served by Waitress in the Docker image)
- **Frontend**: server-rendered templates with Bootstrap and vanilla JavaScript; drag-and-drop with SortableJS (both vendored, no CDN)
- **Storage**: flat JSON files read and written through DuckDB (no database server) — single-user, self-hosted
- **Deployment**: Docker

## Roadmap (summary)

- **Phase 1 — MVP** (built): load an existing layout, browse and search it, link the collection to Discogs, configure cabinets and shelves, generate a sorting proposal (curated clusters, era bands by the decade an artist started, artist families), and adjust it by hand
- **Phase 2 — Ongoing use** (built): syncing with Discogs, album covers and artist pictures, a suggested spot for new purchases, a notice when a purchase would shift an artist's cluster, suggested families and location rules, and the showcase
- **Phase 3 — Refinement** (started): song-level search, a Dutch translation and one screen for moving albums are built; a calmer proposal is built and a plan to carry it out a table full at a time is described; deeper musical-kinship logic and other media formats are not started

Full details, data model, and UI design are in [`docs/requirements.md`](docs/requirements.md).

## AI Transparency

AI tools, including Claude by Anthropic, were used during
the development of this project.

See [AI_DISCLOSURE.md](./AI_DISCLOSURE.md) for details.

## License

Sleeve & Shelf is licensed under the [MIT License](LICENSE).
