# Settings

## ⚙️ Settings

The **Settings** screen edits `config.yaml` in your data folder:

| Setting | Default | What it does |
| --- | --- | --- |
| Base width per disc | 0.5 cm | A single LP in a standard sleeve. A double album counts twice |
| Extra per 180-gram disc | 0.15 cm | Added per disc for heavy vinyl |
| Extra for a gatefold sleeve | 0.2 cm | Added once per album, not per disc |
| Showcase fill | 60 % | How much of a top-loader's width albums may take, leaving room to flip through |
| Count a bundle such as "CD + LP" as vinyl | on | Applies the next time a Discogs export is imported |
| Discogs personal access token | — | Shown masked; paste a new one to replace it |

Saving the width figures estimates every album's width again. Shelf widths are not touched — those are yours.

At the top the screen shows how many centimetres your albums need, how many your shelves offer, and the difference: the quickest way to see whether the estimates add up.

## 🧮 Album widths

Under **Cabinets → Album widths** you enter the real width of the albums the app can't estimate: box sets and bundles, which otherwise count as loose discs. An album you measured keeps that width; clearing it goes back to the estimate.

## 🔒 Visitors and your password

Without a password the app is open: anyone who can reach it can change everything — fine on your own network. Set a password under **Settings → Owner's password**, and everyone else becomes a **visitor**: they can search and browse your collection, open an album's or artist's page, listen to previews, and read this guide. Everything else asks for your password.

- **Log in** at the bottom of the menu. A device stays logged in until you **Log out** there.
- The password has at least 12 characters; make it a strong one, as the app can be reached from the internet.
- Changing the password logs out your other devices; this one stays logged in.
- **Forgot it?** On the server, set a new one from the command line:

    ```sh
    uv run python -m sleeve_shelf set-password
    ```

    or, in Docker, `docker exec -it sleeve-shelf python -m sleeve_shelf set-password`. With `--remove` the app is open again.

After a few wrong passwords each next try has to wait a little longer, so nobody can keep guessing. A visitor who plays a great many previews in a short time is asked to wait a few minutes, and one who opens hundreds of pages a minute is asked to wait a minute — far more than anyone browsing by hand. You, logged in, have no limit.

## 🌗 Light or dark

The app follows your device's light or dark setting. Settings has a switch to choose for this device only; it is remembered in the browser, not in your data. The version of the app is shown below it.
