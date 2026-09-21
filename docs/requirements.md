# Requirements — Sleeve & Shelf

*As of: September 21, 2026*

**Sleeve & Shelf** is a self-hosted, open-source Python Flask web application (Bootstrap + JavaScript) that organizes a vinyl collection (~1,190 vinyl titles out of ~1,455 tracked releases on Discogs) across a record cabinet, based on musical kinship, artist era, and physical shelf space.

> The Discogs collection CSV export contains no style/genre data and no original-release-year data (see [Sorting logic](#sorting-logic) and [Data model](#data-model)) — both are fetched from the Discogs API during import. Confirmed against a real export on 2026-09-20.

## Goal, scope, and phasing

### Phase 1 — MVP

- CSV import of a Discogs export; vinyl is detected by parsing the free-text `Format` field (tokens such as `LP`, `7"`, `10"`, `12"`, optionally prefixed with a quantity like `2x`) — there is no simple `Format == "Vinyl"` check. Whether a "bonus disc" bundle (e.g. `"CD + LP"`) counts as vinyl is a configurable setting, not a hardcoded rule — see Configuration
- **Discogs API enrichment during import**: for each vinyl release, fetch its styles and `master_id` from the release endpoint, then fetch the original release year from the master endpoint — required because the CSV export provides neither (see [Sorting logic](#sorting-logic)). This needs its own wizard step to configure the personal access token, moved up from Phase 2 into Phase 1
- Enrichment results (styles, master ID, original year) are cached locally per `release_id`/`master_id` so re-running the wizard or re-importing doesn't repeat already-fetched API calls
- Manage storage structure: cabinets and shelves (width in cm, type top-loader/front-loader, layer top/bottom, reachability score, showcase flag for top-loaders)
- Manually create artist alias/project groups (e.g. related projects by the same person)
- Manually configure location rules: fixed exceptions (artist, alias group, or style → mandatory cabinet), separate from the automatic proposal
- Generate a sorting proposal following the sorting logic (see below)
- Proposal is fully adjustable by hand (move between shelves, reorder)
- Onboarding wizard for first-time setup
- No album covers — the standard Discogs CSV export does not include cover URLs, and cover art is out of scope for the Phase 1 API enrichment (kept for Phase 2, see below)
- **Browse/Search screen**: a dedicated main-nav screen for browsing the collection digitally, in *crate-digging* mode — it follows the actual physical order (cabinet → shelf → position) from the current placement, i.e. scrolling through it mirrors flipping through the real shelves. Includes search by artist and album (title-only search; no tracklist data is fetched, so song-level search is out of scope for Phase 1 — see Phase 3)

### Phase 2 — Ongoing management

- **Live/ongoing** Discogs API integration: the one-time enrichment already happens in Phase 1 — Phase 2 extends this to keep the collection in sync (new purchases, changed collection data) rather than only at first import
- Add album covers to the Layout screen (Album gets a cover_url field)
- Add new purchases, with a suggested spot within the existing layout
- Suggestions for new location rules based on the existing layout — always requiring confirmation, never applied automatically
- Showcase management for the top-loaders (rotating samples from the collection)
- Notification + confirmation when a new purchase would shift an existing artist's dominant style (and thus its cluster)

### Phase 3 — Refinement

- Further refinement of musical kinship, independent of Discogs style tags
- Song-level search: fetch and store tracklist data per release (via the Discogs API) so the Browse/Search screen (Phase 1) can also match on song titles
- Additional language catalogs (e.g. Dutch) — the MVP ships `en` only, but is structured (Flask-Babel) so this is adding a catalog, not a rebuild
- Possibly later: other media formats (CD, etc.)

### Non-functional requirements

- Open source
- Single-user application
- Onboarding/guidance as an ongoing design principle for non-technical users — not just for the Discogs API integration, but also for setting up the storage structure and CSV import
- Self-hosted, deployed via Docker containers
- Strict separation of concerns: the sorting engine, persistence, and web layer are independent of each other
- The Discogs API is rate-limited (60 requests/minute, authenticated); enriching ~1,190 vinyl releases (styles + master lookups) takes on the order of 30–40 minutes on first import. The wizard must show progress and must not have to be re-run from scratch if interrupted — cached results are reused
- The Discogs personal access token is a credential: it lives only in `config.yaml` (git-ignored, never committed) and is never shown in full in the UI once set (see Configuration)
- **Light and dark theme**: follows the device's system preference by default, with a manual toggle to override it. The preference is remembered per device (browser-local), not synced across devices or stored in `config.yaml`
- **Responsive / mobile-friendly**: the whole app is usable on a phone, but this matters most for the Browse/Search screen (see UI) — browsing is something you'd realistically do standing in front of the actual shelves, phone in hand
- **Language**: English is the primary and only shipped language for the MVP. Multi-language support is not needed now but is a real option for a later phase, so the MVP is built i18n-ready from the start (see Architecture) rather than retrofitted later. Discogs data itself (styles, genres) stays in English regardless of UI locale — that's external source data, not app copy, and isn't part of this requirement

## Sorting logic

### 1. Clustering by musical kinship (style)

- Style tags are not present in the Discogs CSV export — they are fetched per release from the Discogs API during import (see Phase 1)
- Each artist gets one dominant Discogs style, based on the most albums in that style within the collection
- In case of a tie: the style of the earliest album (original release year) is decisive
- An artist always stays together as a whole — never split across clusters
- Style clusters are ordered relative to each other based on co-occurrence: styles that frequently appear together for artists with multiple albums in the collection are placed closer to one another
- Alias/project groups are treated as separate units within the cluster of their own dominant style

### 2. Era bands per artist

- The CSV's `Released` field is the year of the specific pressing owned, not the original release year (confirmed example: the 1980 reissue of David Bowie's *Space Oddity*, originally released 1969, is listed as `1980` in the export). The original release year is fetched via the Discogs API: release → `master_id` → master's year
- Dynamic per artist: early/middle/late based on the spread of release years (original release year) within that artist's discography in the collection — not fixed decades
- An artist with a single album gets a single band (no early/middle/late split)
- Alias groups: each project gets its own era breakdown, not merged into a single timeline
- Alphabetical by album title within each era band

### 3. Physical placement

- Shelf width in cm determines how many records fit
- Each album's estimated width is computed from its `Format` tokens (the same ones already parsed for vinyl detection — see Phase 1), but only for a **simple** format string — one with no `+` and no `Box` token:
  - Base width: **0.5 cm** per disc (standard-weight 12" LP, single sleeve)
  - 180-gram surcharge: **+0.15 cm** per disc where the format includes `180`
  - Gatefold surcharge: **+0.2 cm** per release where the format includes `Gat` (applied once per release, not per disc — a gatefold sleeve folds around all its discs)
  - Disc count comes from the existing quantity prefix (e.g. `2xLP` → 2 discs)
  - These figures, and the ones below, live in `config.yaml` (see Configuration) — not hardcoded, so they can be tuned without a code change
- A **compound format** (contains `+`, e.g. `"LP + 12\""`, or a `Box` token, e.g. `"6xLP, Comp, Cle + Box"`) does not get an automatic estimate — box sets and multi-release bundles vary too much in physical size to model from format tokens alone. Instead:
  - `manual_width_cm` on the album (see Data model) holds the real width, set by hand
  - Until set, a rough fallback (disc count × base width, no surcharges) is used so the album can still be placed — non-blocking, following the same pattern as unconfirmed style assignments (see §4)
  - The album is flagged in "Openstaande bevestigingen" (Dashboard) as needing a manually confirmed width
- A style cluster may span adjacent shelves within the same cabinet if it doesn't fit on one shelf
- Reachability only plays a role through the explicit, manually configured location rules — not as a general rule for popular/frequently-picked artists

### 4. Stability and confirmation

- Any shift of an artist to a different style cluster (triggered by new purchases) is always presented for confirmation first — never applied silently
- The same applies to suggested new location rules: always requiring confirmation, never automatic
- **Exception during first-time setup (wizard)**: for the very first layout of the full collection, all style assignments are automatically bulk-accepted (individually confirming ~1089 assignments isn't workable); the user corrects individual ones afterward as needed

## Data model

**Core entities**

- **Artist**: id, name, Discogs artist ID (optional), alias_group_id (nullable)
- **AliasGroup**: id, label — links multiple Artists treated as related-but-separate projects
- **Album**: id, artist_id, title, Discogs `release_id` (from CSV), Discogs `master_id` (fetched), original release year (fetched via master), `format_tokens` (parsed from the CSV `Format` field — disc count, 180-gram, gatefold, compound/`Box` flag, and other qualifiers), computed width (cm, derived from `format_tokens` for simple formats — see Sorting logic §3), `manual_width_cm` (nullable — set by hand for compound/box formats, overrides the computed value when present), `width_confirmed` (bool — false for compound formats until manually set), list of styles (fetched via release), cover_url (empty until phase 2)
- **Style**: id, name (from Discogs)

**Discogs enrichment cache** (avoids re-fetching on every import/wizard run)

- **ReleaseEnrichment**: release_id, styles, master_id, fetched_at
- **MasterEnrichment**: master_id, original_release_year, fetched_at

**Sorting/clustering**

- **ArtistStyleAssignment**: artist_id, style_id (dominant style), confirmed (bool) — distinguishes a proposed dominant style from a confirmed one
- **StyleClusterOrder**: the computed (co-occurrence) ordering of styles — can be recomputed on the fly, doesn't need to be persisted

**Storage structure**

- **Cabinet**: id, name, location (room)
- **Shelf**: id, cabinet_id, width (cm), type (top-/front-loader), layer, reachability score, is_showcase (bool)
- **LocationRule**: id, target (artist_id, alias_group_id, or style_id), mandatory cabinet_id, note — always created manually

**Placement**

- **Placement**: unit (artist_id or alias-member), shelf_id, order position within the shelf, source (algorithm proposal vs. manually overridden)

## Architecture, storage, and deployment

### Layers (separation of concerns)

1. **Ingestion**: a CSV parser (detects vinyl by parsing the `Format` field) and a Discogs API client (fetches styles + original release year per release/master, used for import-time enrichment from Phase 1 onward, and for ongoing sync from Phase 2) — both produce the same internal Album/Artist structure
2. **Domain**: the entities above, as plain domain objects, independent of storage
3. **Sorting engine**: pure logic in small, self-contained steps (determining dominant style, co-occurrence clustering, computing era bands, placement/width allocation) — operates on domain objects, with no knowledge of the database or web layer
4. **Persistence**: storage of all entities, independent of the sorting engine
5. **Web**: Flask routes/blueprints + Bootstrap/JS templates, including the onboarding wizard. Light/dark theming uses Bootstrap 5.3's built-in `data-bs-theme` attribute rather than a custom theming layer — the toggle just switches that attribute and writes the choice to browser-local storage. UI copy goes through Flask-Babel (`gettext`/`_()`) from the start, with only an `en` catalog shipped in the MVP — this is the i18n-readiness the Language requirement calls for: adding a second language later means adding a `.po` catalog, not restructuring templates
6. **Confirmation layer**: a separate piece of logic that tracks proposals requiring confirmation (new style assignment, new location rule)

### Storage: files (JSON/CSV), no database

**Master data** (overwritable, no history needed):

- `artists.json`, `alias_groups.json`, `albums.json`, `cabinets.json`, `shelves.json`, `location_rules.json`, `style_assignments.json`, `discogs_cache.json` (release/master enrichment cache — see Data model)

**Layout with history**:

- `placement_current.json` — active working state, overwritten on every change, no history
- `placements/` — directory of full snapshots, only created when the user explicitly chooses to "save this layout"; every snapshot is kept forever (no limit, no cleanup)

### DuckDB as the read/write layer

- The persistence layer uses DuckDB (`read_json_auto()` / `COPY ... TO '...json'`) to read and write the JSON files via SQL, instead of Python's `json` module — queries, joins, and aggregations (e.g. dominant-style determination, style co-occurrence, era-band spread) run as SQL against the JSON files
- DuckDB operates directly on the plain JSON files; there is no separate `.duckdb` database file
- **Explicitly out of scope**: Parquet and Delta Lake. At this scale (a single user, a personal collection, a handful of saved layouts) their benefit — avoiding full-copy storage across many versions — doesn't apply, while their cost (binary, non-diffable files; extra complexity) works directly against the project's goal of keeping the data human-readable and inspectable. The full-JSON-snapshot-per-save approach stays as is

### Configuration

- `config.yaml`, read and written with plain PyYAML — not through the DuckDB layer above, since this is scalar application settings, not queryable collection data
- Holds:
  - The width-estimation constants (base width, 180-gram surcharge, gatefold surcharge — see Sorting logic §3)
  - The Discogs personal access token
  - `count_bonus_discs_as_vinyl` (bool, default `true`) — whether a "bonus disc" bundle such as `"CD + LP"` is treated as vinyl during import (see Phase 1); defaults to the current any-segment-matches behavior, but is a setting rather than a hardcoded rule, since it's genuinely a judgment call
- Editable from a dedicated **Settings** screen in the web app (see UI), in addition to being written once by the onboarding wizard (Phase 1, step 4) when the token is first configured
- **Never committed to version control** — `config.yaml` is git-ignored, since it holds a credential. The Settings screen shows the API token masked (last 4 characters only), with a "replace" action rather than displaying it in full

### Deployment

- Self-hosted, deployed via Docker containers
- File storage (JSON) mounted as a volume, so data persists outside the container

## Onboarding wizard

Strictly linear flow on first use; once completed, the regular application is freely navigable.

1. **Welcome/intro**
2. **Set up storage structure** — cabinets + shelves (type, layer, width, reachability, showcase flag)
3. **Import collection** — explanation of the Discogs CSV export, upload, automatic filtering to vinyl (by parsing the `Format` field), preview of counts
4. **Discogs API enrichment** — personal access token setup, then fetch styles and original release years for every vinyl release (release → master lookups), with progress shown; safe to resume thanks to local caching
5. **Alias/project groups** (optional, may be left empty)
6. **Location rules** (optional, may be left empty)
7. **First sorting proposal** — all style assignments are bulk-accepted, the full proposal (including placement) is shown immediately, individually correctable
8. **Save** — explicit action; the first version lands in `placements/`

## UI / screen layout

### Main navigation (after the wizard)

- **Dashboard** — overview: number of records, cabinets/shelves, last saved version
- **Layout** — core screen (see below)
- **Browse/Search** — crate-digging view of the collection, following the actual physical shelf order; search by artist and album (see Phase 1). This supersedes the earlier decision to have no separate "Collection" nav item — that assumption no longer holds now that browsing/search is its own dedicated feature, not just a detail drill-down from Layout
- **Storage structure** — manage cabinets/shelves
- **Alias groups** — management screen
- **Location rules** — management screen
- **Showcase** — manage top-loaders/samples (phase 2)
- **Versions** — saved layouts, with the option to restore
- **Settings** — edit `config.yaml`: width-estimation constants and the Discogs API token (masked, with a replace action)

Album/artist detail is still reachable both from Layout (clicking an artist/era band) and from Browse/Search.

### Layout screen (core)

- One tab/dropdown per location (room); within a location, all cabinets in that room are stacked underneath one another
- Each cabinet shows its shelves, with a filled bar visualizing the occupied width
- Plain text in phase 1 (artist, era band, record count); album covers are only added in phase 2 (affects display only, not the data model)
- Drag-and-drop (e.g. via SortableJS) between or within shelves adjusts order/placement
- Clickable through to album/artist detail from an artist/era band

### Browse/Search screen

- Crate-digging mode: renders the collection in physical order (cabinet → shelf → position within shelf), based on the current `Placement` data — scrolling through it mirrors flipping through the real shelves
- Search bar filtering by artist or album title (Phase 1); song-level search added once tracklist data is fetched (Phase 3)
- Plain text in Phase 1, same as Layout — covers follow the same phase-2 timeline
- **Mobile is the priority form factor for this screen** in particular — realistically used standing in front of the shelves: single-column layout, touch targets sized for tapping (prev/next shelf, search field), and the search bar / breadcrumb stay reachable without scrolling back up (e.g. sticky positioning)

### Detail screen (artist/album)

- Reachable from both Layout and Browse/Search (clicking an artist/era band or a search result)
- Shows the dominant style with its confirmation status, and an action to correct it
- Shows an active location rule for the artist/alias group, if any
- Shows each era band's albums (title, original release year, current shelf)
- **Width confirmation action**: for an album with `manual_width_cm` unset (compound/box format — see Sorting logic §3), the screen surfaces the fallback estimate and lets the user enter the real width by hand. This is the actual place the "Openstaande bevestigingen" width flag (Dashboard) resolves to — Settings only holds the global constants, not per-album overrides
- Action to move the album/artist to a different shelf

## Open questions

- **Vinyl detection edge case**: whether a "bonus disc" bundle (e.g. `"CD + LP"`) counts as vinyl is now a configurable setting (`count_bonus_discs_as_vinyl`, default `true` — see Configuration) rather than a fixed rule, so this no longer needs to be settled up front
- **Width-estimation constants**: the 0.5 cm base / +0.15 cm (180g) / +0.2 cm (gatefold) figures (see Sorting logic §3) are an untested starting assumption, now configurable in `config.yaml` — to be tuned against real shelf measurements
