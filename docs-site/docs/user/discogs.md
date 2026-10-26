# Discogs

The **Discogs sync** screen brings your collection in from [Discogs](https://www.discogs.com/) and keeps it up to date with **one button**, *Sync*. A round runs in the background, and the screen shows each of its steps as it goes: a turning ring for the step it is on, a tick for what is done, a bar for how far it is. You can leave the page; the round goes on, and pressing *Sync* again while it runs starts nothing new. What only you can decide shows afterwards under **Waiting for you**.

## 🔑 Your access token

The app talks to Discogs with a personal access token. Create one on discogs.com under *Settings → Developers → Generate new token*, and paste it on the Discogs screen or under Settings. It is kept in `config.yaml` in your data folder; the app only ever shows its last four characters.

## 🔄 Syncing your collection

A round has four steps:

1. **Fetch your collection** — a hundred releases a second; the bar shows the pages, of how many, and how many releases your collection holds.
2. **Compare and take over** — new vinyl becomes albums without a place, with their covers. Nothing is removed or moved: an album no longer on Discogs is only marked, and a release that only looks like one of your albums waits for you. The step then says what changed: new albums, formats brought up to date, albums no longer on Discogs, matches to confirm.
3. **Fetch styles, years, tracklists and pictures** — only what is not in yet (see below), so after the first time this takes seconds.
4. **Store covers and pictures here** — so they show without a connection.

*Stop* ends a round; the next one goes on where it stopped, as nothing is fetched twice.

A sync also brings the format of albums already linked up to date (disc count, 180 gram, gatefold), so their estimated width follows. A width you measured yourself is left alone.

!!! tip "Without the API"
    You can also import a Discogs collection export (CSV) instead of syncing — under *Or import a Discogs export*, which shows what it would do before anything changes — or load one from the command line. Afterwards *Only fetch, without syncing* fetches what the export doesn't bring:

    ```sh
    uv run python -m sleeve_shelf import-discogs path/to/collection.csv
    ```

## ✅ Confirming matches

Albums from your workbook are linked to Discogs releases by artist and title. When that is not certain, the closest release is only *proposed*, under **Waiting for you**: confirm it if it is the same album, or turn it down. Until then the album stays where it is and can be browsed as usual.

## ⬇️ Fetching styles, years and pictures

The fetch run asks Discogs, per release, for its styles, its tracklist and its original release year — the year of the first pressing, not of your copy — and per artist for its picture and who it is connected to. A release fetched before tracklists — or the writers of its songs — were kept is asked for once more, for its tracklist only: its styles and year stay as they were, so nothing on your shelves moves because of it. Discogs allows about one request a second, so the first run takes a while; a progress bar keeps up, and you can stop and start again without losing anything. Last of all, covers and pictures are stored in your data folder, so they also show without a connection.

A year you looked up and confirmed yourself is never overwritten.

## 👋 Albums that left Discogs

When a sync no longer finds a release in your Discogs collection — sold, or removed — the album is marked and listed under **Waiting for you**. It stays on its shelf. For each one you either say you **still have it** (it is not asked about again) or **remove** it, which asks for confirmation first and keeps a version of the layout from before.
