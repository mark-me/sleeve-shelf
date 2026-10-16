# Getting started

## 🚀 Running the app

Sleeve & Shelf runs on your own machine or server and keeps everything in one data folder. With [uv](https://docs.astral.sh/uv/) installed:

```sh
uv run python -m sleeve_shelf
```

Then open <http://127.0.0.1:5000>. These environment variables change how it runs:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SLEEVE_SHELF_DATA_DIR` | `data` | Where the collection is kept |
| `SLEEVE_SHELF_HOST` | `127.0.0.1` | Set to `0.0.0.0` to reach the app from your phone |
| `SLEEVE_SHELF_PORT` | `5000` | The port to listen on |
| `SLEEVE_SHELF_PROXIES` | — | Behind Tailscale Funnel or a reverse proxy: `1` |

!!! note "Restart after an update"
    The app reads its page templates once, when it starts. After updating, restart it to see the changes.

## 🐳 With Docker

```sh
docker run -d --name sleeve-shelf -p 5000:5000 \
  -v sleeve-shelf-data:/data ghcr.io/mark-me/sleeve-shelf:latest
```

Your collection lives in the `/data` volume, so it survives updates of the container. Compose examples are in the `docker/` folder of the repository.

## 🌱 First start

On the first visit the app offers two ways in.

**You already worked out a layout.** Upload the Excel workbook in which you keep your cabinet layout (`docs/import_example.xlsx` in the repository shows the expected shape). The app reads your cabinets, shelves, clusters and albums from it, shows a preview, and opens on Browse / Search once you confirm. Nothing else needs to be set up.

**You start from your Discogs collection.** Without a workbook you enter your cabinets and shelves yourself, bring in your collection from Discogs, and let the app propose a layout. The Dashboard lists the steps in order.

!!! tip "When the browser can't upload"
    Some managed computers block file uploads in the browser. Load the workbook from the command line instead; the running app picks it up straight away:

    ```sh
    uv run python -m sleeve_shelf load path/to/layout.xlsx
    ```

## 📱 On your phone

The app is made to be used in front of your cabinet. On a phone the menu folds away behind the ☰ button, and Browse / Search shows one shelf at a time with *Previous shelf* and *Next shelf* at the bottom.

You can install it on your home screen like an app. Browsers only offer that over **HTTPS** (or on `localhost`), so put the app behind something that provides HTTPS — Tailscale, or a reverse proxy. Installed, it opens on Browse / Search, without the browser's address bar.
