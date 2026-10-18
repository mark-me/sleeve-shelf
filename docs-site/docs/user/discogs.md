# Discogs

The **Discogs sync** screen brings your collection in from [Discogs](https://www.discogs.com/) in three steps, from top to bottom. The step that waits for you is marked.

## 🔑 Your access token

The app talks to Discogs with a personal access token. Create one on discogs.com under *Settings → Developers → Generate new token*, and paste it on the Discogs screen or under Settings. It is kept in `config.yaml` in your data folder; the app only ever shows its last four characters.

## 🔄 Syncing your collection

*Sync* fetches your Discogs collection — about a second per hundred releases — and shows what it would do before anything changes: how many vinyl releases, how many are linked to albums you already have, what is new, and what is no longer in your Discogs collection. Taking it over adds the new vinyl as albums without a place, and brings the covers.

A sync also brings the format of albums already linked up to date (disc count, 180 gram, gatefold), so their estimated width follows. A width you measured yourself is left alone.

!!! tip "Without the API"
    You can also upload a Discogs collection export (CSV) instead of syncing, or load one from the command line:

    ```sh
    uv run python -m sleeve_shelf import-discogs path/to/collection.csv
    ```

## ✅ Confirming matches

Albums from your workbook are linked to Discogs releases by artist and title. When that is not certain, the closest release is only *proposed*: confirm it if it is the same album, or turn it down. Until then the album stays where it is and can be browsed as usual.

## ⬇️ Fetching styles, years and pictures

The fetch run asks Discogs, per release, for its styles, its tracklist and its original release year — the year of the first pressing, not of your copy — and per artist for its picture and who it is connected to. A release fetched before tracklists were kept is asked for once more, for its tracklist only: its styles and year stay as they were, so nothing on your shelves moves because of it. Discogs allows about one request a second, so the first run takes a while; a progress bar keeps up, and you can stop and start again without losing anything. Last of all, covers and pictures are stored in your data folder, so they also show without a connection.

A year you looked up and confirmed yourself is never overwritten.

## 👋 Albums that left Discogs

When a sync no longer finds a release in your Discogs collection — sold, or removed — the album is marked and listed on this screen. It stays on its shelf. For each one you either say you **still have it** (it is not asked about again) or **remove** it, which asks for confirmation first and keeps a version of the layout from before.
