# Architecture

## 🏛️ Layers

```mermaid
flowchart TB
    web["<b>web/</b><br/>blueprints, templates, static"]
    services["<b>application services</b><br/>collection, discogs_import, enrichment,<br/>proposal, placing, storage, widths, …"]
    sorting["<b>sorting/</b><br/>pure functions: eras, families,<br/>order, placement, spots"]
    ingestion["<b>ingestion/</b><br/>workbook, Discogs CSV, Discogs API"]
    persistence["<b>persistence/</b><br/>JsonStore, Browse queries (DuckDB)"]
    domain["<b>domain/</b><br/>plain dataclasses"]

    web --> services
    services --> sorting
    services --> ingestion
    services --> persistence
    sorting --> domain
    ingestion --> domain
    persistence --> domain
```

| Path | What it holds |
| --- | --- |
| `src/sleeve_shelf/domain/` | Plain dataclasses, standard library only. No storage or web knowledge. |
| `src/sleeve_shelf/ingestion/` | Reading the outside world: the layout workbook, the Discogs CSV export, the Discogs API, the format-string parser. |
| `src/sleeve_shelf/sorting/` | The sorting engine: pure functions on domain objects. |
| `src/sleeve_shelf/persistence/` | `JsonStore` (one JSON file per entity) and the read queries for Browse. |
| `src/sleeve_shelf/*.py` | Application services that tie the layers together, such as `placing` (moving albums by hand, location rules), `storage` (cabinets and shelves), `taking_part` (which albums are sorted and which shelves a proposal fills), `network` (what ties artists together, for Connections). |
| `src/sleeve_shelf/web/` | Flask blueprints, templates, static files. One blueprint per screen. |

A blueprint never writes to the store itself: it reads and checks the form, calls a service, and turns the service's outcome into a page or a redirect. Business rules — *only an empty shelf can be removed*, *nothing drops off a shelf during a drag* — live in the services, where they have tests of their own.

!!! warning "A service and a blueprint can share a name"
    `sleeve_shelf/storage.py` and `sleeve_shelf/web/storage.py`, likewise `versions`. In web modules import names explicitly — `from sleeve_shelf.storage import save_shelf` — not `from sleeve_shelf import storage`, which can resolve to the blueprint.

## 🧵 A request, start to finish

Dragging a block on the Layout screen, as an example:

```mermaid
sequenceDiagram
    participant B as Browser (layout.js)
    participant W as web/layout.py
    participant P as placing.py
    participant V as versions.py
    participant S as JsonStore
    B->>W: POST /layout/move {shelf: [album ids]}
    W->>P: rearrange_shelves(store, contents, off_shelf)
    P->>S: load Placement, Album, Shelf
    alt an album would drop off a shelf
        P-->>W: ShelvesChanged
        W-->>B: 409 "reload the page"
    else
        P->>V: keep_restore_point
        P->>S: save Placement
        W->>S: shelf fill (DuckDB)
        W-->>B: 200 {how full each shelf now is}
    end
```

## 🍔 The menu and its counts

The five menu sections and their tabs are declared once, in `web/navigation.py`; a new screen gets its tab there. Each section also has an icon, named after the section's key, in the sprite `web/static/vendor/menu-icons.svg`, which also holds those of Help, logging in and out, and the language at the end of the menu.

What waits for a decision — matches, family suggestions, albums without a place, shelves over a measured width — is counted in one place, `web/waiting.py`. The counts feed both the Dashboard and the numbers in the menu. Working them out takes a while (family suggestions compare every artist with every other), so they are kept until a data file or `config.yaml` changes.

Each tab also names the part of the user guide that explains its screen, as `help="user/shelves/#layout"`; pages that share a tab but have their own part are in `PAGE_HELP`. The **?** beside the tabs links there. The app serves the documentation site itself under `/help/` (`web/help.py`): the Docker image builds it with Zensical and carries it in `/app/help`; a local run uses `docs-site/site` once built, and GitHub Pages otherwise. `tests/test_help.py` checks that every page and anchor named exists — rename a heading in the guide and the test says which screen to update.

Screens that need a collection are listed in `NEEDS_COLLECTION` in `src/sleeve_shelf/__init__.py`; without a collection they lead to the setup wizard.

## 🛡️ Visitors and the owner

With a password set (`access.py`, kept hashed in `config.yaml`), `web/login.py` runs before every request. The owner — logged in, or anyone while there is no password — may do everything. A visitor may open only the endpoints in `VISITOR_PAGES`, and only with GET; the one thing a visitor may send is the password itself. Any other page redirects to the login, any other POST gets a 403. A screen added later is therefore the owner's by default.

The pages a visitor may open hide their actions behind `{% if is_owner %}`, and the menu shows a visitor only Browse and Help (`navigation.visible_sections`). The session cookie is HTTPS-only (`SLEEVE_SHELF_HTTP_LOGIN=1` allows plain HTTP for a local try-out), signed with a key made once per installation (`data/session_key`), and holds the owner's login key (`owner_login_key` in `config.yaml`): random, made anew with every password and cleared with it, so changing the password logs out the other devices, and nothing in the cookie comes from the password. A password set before keys were kept gets one at the next login. Failed logins wait longer per address, and a visitor's listening, which asks Deezer on the app's behalf, is limited per address. The address is `request.remote_addr`: only with `SLEEVE_SHELF_PROXIES` set — the number of proxies before the app, 1 behind Tailscale Funnel — does Werkzeug's `ProxyFix` take it from `X-Forwarded-For`, from the entry the trusted proxy added. Without it a forwarded address is ignored, as a client could write a new one with every request. A login gets the key read together with the hash that was verified (`access.verified_key`), compared in constant time, and the session key is written whole or not at all. Going back to a page after logging in or choosing the language goes through `login.redirect_within`, which only follows a path of this app. A saved layout version is only ever a plain file name in `placements/` (`JsonStore._snapshot_path`).

## 🪜 Headers and other sites' forms

`web/security.py` adds to every response a Content-Security-Policy: a page runs only the app's own scripts and inline scripts carrying this request's nonce (`{{ csp_nonce() }}` in a template), and loads images, sound and video only from Discogs, Deezer and youtube-nocookie. Inline handlers such as `onchange="…"` do not run; `static/page.js` handles `data-submit-on-change` instead. Go to cabinet… on Layout is a form too: `layout.go` makes the address and redirects, so no script goes to an address it read from the page. Nothing may show the app in a frame. The help, being the documentation site, has a looser policy of its own.

A change — any request other than GET or HEAD — must come from a page of the app: `Sec-Fetch-Site` must be `same-origin`, or, from a browser too old to send it, `Origin` must be this host. A request with neither is not a browser's, so nobody can be tricked into sending it.

## 🖼️ Covers and pictures

Covers and artist pictures are hotlinked from Discogs until the fetch run has stored them in `data/covers/albums/` and `data/covers/artists/`. The template filter `local_cover` picks the stored copy when there is one. Every page has to work without them. Pictures a user adds are kept apart in `data/artist_pictures/`, with a small copy made by Pillow, and are never touched by a sync.
