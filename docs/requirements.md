# Requirements — Sleeve & Shelf

*As of: October 7, 2026*

**Sleeve & Shelf** is a self-hosted, open-source Python Flask web application (Bootstrap + JavaScript) that organizes a vinyl collection (~1,190 vinyl titles out of ~1,455 tracked releases on Discogs) across a record cabinet, based on musical kinship, artist era, and physical shelf space.

> The Discogs collection CSV export contains no style/genre data and no original-release-year data (see [Sorting logic](#sorting-logic) and [Data model](#data-model)) — both are fetched from the Discogs API during import. Confirmed against a real export on 2026-09-20.

## Goal, scope, and phasing

### Phase 1 — MVP

The MVP is delivered in two steps. The record cabinet has already been laid out by hand, so the first need is to get that existing layout into the app and browse it (1a); having the app generate and maintain a layout itself comes second (1b).

#### Phase 1a — Import & Browse

- **Initial load**: seed the collection and its layout from an already-worked-out XLSX workbook (example: `docs/import_example.xlsx`) — see [Initial load](#initial-load). This is the only import in 1a: no Discogs CSV, no Discogs API, no access token. Uploading again replaces everything loaded before
- **Browse/Search screen**: a dedicated main-nav screen for browsing the collection digitally, in *crate-digging* mode — it follows the actual physical order (cabinet → shelf → position) from the current placement, i.e. scrolling through it mirrors flipping through the real shelves. Includes search by artist and album (title-only search; no tracklist data is fetched, so song-level search is out of scope for Phase 1 — see Phase 3)
- **Unplaced albums** list: spreadsheet rows without a spot on a shelf stay visible rather than being dropped (see [Initial load](#initial-load))
- A short onboarding wizard: welcome → upload spreadsheet → browse (see [Onboarding wizard](#onboarding-wizard))

#### Phase 1b — Sorting

Everything the app needs to propose and maintain a layout itself. Builds on the data loaded in 1a, but also works without it (a user with no spreadsheet starts here).

- **Match the initially loaded albums to Discogs**: once the Discogs export is imported and enriched (next bullets), the albums from the 1a spreadsheet are matched to it, so they gain `release_id`, styles, original year, and width — see [Initial load](#initial-load)
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

### Phase 2 — Ongoing management

- **Live/ongoing** Discogs API integration: the one-time enrichment already happens in Phase 1 — Phase 2 extends this to keep the collection in sync (new purchases, changed collection data) rather than only at first import
- Add album covers to the Layout screen (Album gets a cover_url field)
- Add new purchases, with a suggested spot within the existing layout
- Suggestions for new location rules based on the existing layout — always requiring confirmation, never applied automatically
- Showcase management for the top-loaders (rotating samples from the collection)
- Notification + confirmation when a new purchase would shift an existing artist's dominant cluster

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

### 1. Clustering by musical kinship (cluster)

- Style tags are not present in the Discogs CSV export — they are fetched per release from the Discogs API during import (see Phase 1)
- Raw Discogs styles are not used as clusters directly. Each Style belongs to a user-curated **Cluster** (see Data model) — a display/grouping layer decoupled from Discogs' own taxonomy:
  - When a Style is seen for the first time, it's auto-assigned its own same-named Cluster (1:1) — the app works immediately with no upfront curation required
  - The user can later merge several related Styles into one Cluster (e.g. combining the Discogs styles "Post-Punk", "New Wave", and "Art Rock" into a single "Post-Punk / New Wave / Art Rock" cluster) or rename a Cluster, via the Clusters screen (see UI)
  - This is mostly a **merge** operation, not a split — Discogs' style taxonomy is already fairly granular (e.g. Jazz alone has separate styles like Bop, Hard Bop, Cool, Swing, Modal), so curation is about grouping related granular styles into one browsable cluster, not subdividing a single style
- Each artist gets one dominant Cluster, based on the most albums in that Cluster (via their Styles) within the collection
- In case of a tie: the Cluster of the earliest album (original release year) is decisive
- An artist always stays together as a whole — never split across clusters — **except** via an explicit album-level location rule (see Data model), which detaches one specific title without affecting the rest of the artist's catalog
- Clusters are ordered relative to each other based on co-occurrence: clusters that frequently appear together for artists with multiple albums in the collection are placed closer to one another
- Alias/project groups are treated as separate units within the cluster of their own dominant Cluster
- An artist whose catalog spans too many styles to meaningfully cluster (e.g. a prolific artist covering several genres) can be manually confirmed as **its own standalone cluster**, not tied to any Style — the same manual-override mechanism as correcting a dominant cluster (`ArtistClusterAssignment`), just pointing at the artist itself

### 2. Era bands per artist

- The CSV's `Released` field is the year of the specific pressing owned, not the original release year (confirmed example: the 1980 reissue of David Bowie's *Space Oddity*, originally released 1969, is listed as `1980` in the export). The original release year is fetched via the Discogs API: release → `master_id` → master's year
- **Year sanity check**: the master-year lookup isn't always reliable (e.g. for compilations). The artist's start year is the earliest confirmed original-release-year among their own albums (self-referential, no extra data source needed). For each album: if `|album's master year − artist's start year| > 20`, the artist's start year is used for era-band placement instead of the album's own master year
- Dynamic per artist: early/middle/late based on the spread of release years (original release year, after the sanity check above) within that artist's discography in the collection — not fixed decades
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
- The era band is the smallest unit the proposal places as a whole: an artist that doesn't fit on one shelf continues on the adjacent shelf at an era-band boundary (see Placement in Data model)
- Reachability only plays a role through the explicit, manually configured location rules — not as a general rule for popular/frequently-picked artists

### 4. Stability and confirmation

- Any shift of an artist to a different style cluster (triggered by new purchases) is always presented for confirmation first — never applied silently
- The same applies to suggested new location rules: always requiring confirmation, never automatic
- **Exception during first-time setup (wizard)**: for the very first layout of the full collection, all style assignments are automatically bulk-accepted (individually confirming ~1089 assignments isn't workable); the user corrects individual ones afterward as needed

## Data model

Overview of the persisted entities and their relations; the lists below are authoritative for the details. Solid lines are plain foreign keys. Dashed lines are either polymorphic references (a LocationRule target, a Placement or ShowcaseFeature unit — each row points at exactly one of the connected entities) or lookups by Discogs ID into the enrichment cache. ClusterOrder is left out: it is computed on the fly and not persisted.

```mermaid
erDiagram
    AliasGroup |o--o{ Artist : "groups"
    Artist ||--o{ Album : "has"
    Artist ||--o{ EraBand : "is split into"
    EraBand |o--o{ Album : "contains"
    Album }o--o{ Style : "tagged with"
    Cluster ||--o{ Style : "groups"
    Artist ||--o| ArtistClusterAssignment : "has dominant cluster"
    Cluster |o--o{ ArtistClusterAssignment : "assigned to"
    Cabinet ||--o{ Shelf : "has"
    Cabinet ||--o{ LocationRule : "mandatory cabinet of"
    Shelf ||--o{ Placement : "holds"
    Shelf ||--o{ ShowcaseFeature : "showcases"

    Artist |o..o{ LocationRule : "target"
    AliasGroup |o..o{ LocationRule : "target"
    Cluster |o..o{ LocationRule : "target"
    Album |o..o{ LocationRule : "target"

    Artist |o..o| Placement : "unit"
    EraBand |o..o| Placement : "unit"
    Album |o..o| Placement : "unit"

    Artist |o..o{ ShowcaseFeature : "unit"
    Album |o..o{ ShowcaseFeature : "unit"

    ReleaseEnrichment |o..o{ Album : "release_id"
    MasterEnrichment |o..o{ Album : "master_id"
    MasterEnrichment |o..o{ ReleaseEnrichment : "master_id"

    Artist {
        int id PK
        string name
        int discogs_artist_id "optional"
        int alias_group_id FK "nullable"
    }
    AliasGroup {
        int id PK
        string label
    }
    Album {
        int id PK
        int artist_id FK
        string title
        int release_id "Discogs, from CSV; nullable until matched"
        int master_id "Discogs, fetched"
        int original_release_year "fetched via master"
        object format_tokens "parsed from CSV Format"
        float computed_width_cm "nullable until matched"
        float manual_width_cm "nullable, overrides computed"
        bool width_confirmed
        list style_ids FK
        int era_band_id FK "nullable"
        string cover_url "empty until phase 2"
    }
    Style {
        int id PK
        string name "from Discogs"
        int cluster_id FK
    }
    Cluster {
        int id PK
        string name
    }
    ArtistClusterAssignment {
        int artist_id PK, FK
        int cluster_id FK "null = artist is its own standalone cluster"
        bool confirmed
    }
    EraBand {
        int id PK
        int artist_id FK
        string label "early/middle/late, or as loaded"
        int position "order within the artist"
        string source "algorithm or initial load"
    }
    Cabinet {
        int id PK
        string name
        string location "room, nullable"
    }
    Shelf {
        int id PK
        int cabinet_id FK
        string name "label within the cabinet"
        float width_cm "nullable"
        string type "top-loader or front-loader, nullable"
        string layer "top or bottom, nullable"
        int reachability_score "nullable"
        bool is_showcase "top-loaders only"
    }
    LocationRule {
        int id PK
        string target_type "artist, alias group, cluster or album"
        int target_id FK
        int cabinet_id FK
        string note
    }
    Placement {
        string unit_type "artist, era band or album"
        int unit_id FK
        int shelf_id FK
        int position "order within the shelf"
        string source "algorithm, manual or initial load"
    }
    ShowcaseFeature {
        int shelf_id FK "showcase shelf"
        string unit_type "artist or album"
        int unit_id FK
    }
    ReleaseEnrichment {
        int release_id PK
        list styles "style names"
        int master_id
        datetime fetched_at
    }
    MasterEnrichment {
        int master_id PK
        int original_release_year
        datetime fetched_at
    }
```

**Core entities**

- **Artist**: id, name, Discogs artist ID (optional), alias_group_id (nullable)
- **AliasGroup**: id, label — links multiple Artists treated as related-but-separate projects
- **Album**: id, artist_id, title, Discogs `release_id` (from CSV; nullable — an album seeded by the initial load has only artist and title until it is matched to Discogs in Phase 1b, and the same holds for its `format_tokens` and computed width), Discogs `master_id` (fetched), original release year (fetched via master), `format_tokens` (parsed from the CSV `Format` field — disc count, 180-gram, gatefold, compound/`Box` flag, and other qualifiers), computed width (cm, derived from `format_tokens` for simple formats — see Sorting logic §3), `manual_width_cm` (nullable — set by hand for compound/box formats, overrides the computed value when present), `width_confirmed` (bool — false for compound formats until manually set), list of styles (fetched via release), `era_band_id` (nullable — the EraBand this album falls in, see Sorting/clustering below; empty until a proposal is generated or an initial load is done), cover_url (empty until phase 2)
- **Style**: id, name (from Discogs), `cluster_id` — the Cluster this Style belongs to; auto-assigned to a new same-named Cluster the first time the Style is seen, user-remappable afterward (see Sorting logic §1)
- **Cluster**: id, name — a user-curated display/grouping layer, decoupled from Discogs' own style taxonomy; starts 1:1 with Styles, can be renamed or have several Styles merged into it via the Clusters screen (see UI)

**Discogs enrichment cache** (avoids re-fetching on every import/wizard run)

- **ReleaseEnrichment**: release_id, styles, master_id, fetched_at
- **MasterEnrichment**: master_id, original_release_year, fetched_at

**Sorting/clustering**

- **ArtistClusterAssignment**: artist_id, cluster_id (dominant cluster — either derived from the artist's most common Style's Cluster, or a standalone cluster pointing at the artist itself), confirmed (bool) — distinguishes a proposed dominant cluster from a confirmed one
- **EraBand**: id, artist_id, label, position (order of the band within the artist's timeline), source (algorithm vs. initial load) — one band of an artist's discography (see Sorting logic §2); albums point at their band via `era_band_id`. The label is free text: the sorting engine produces early/middle/late (or a single band for a single-album artist), while an initial load stores the spreadsheet's own labels as-is (e.g. "1990s" — see [Initial load](#initial-load)). Each artist has its own bands, so alias-group members are never merged into a single timeline. Unlike ClusterOrder, era bands are persisted: bands seeded by an initial load can't be recomputed, and regenerating a proposal replaces them with algorithm-computed ones
- **ClusterOrder**: the computed (co-occurrence) ordering of clusters — can be recomputed on the fly, doesn't need to be persisted

**Storage structure**

- **Cabinet**: id, name, location (room; nullable — not known after an initial load)
- **Shelf**: id, cabinet_id, name (the label of the shelf within its cabinet, e.g. "a"), width (cm), type (top-/front-loader), layer, reachability score, is_showcase (bool). Width, type, layer, and reachability are nullable: a shelf seeded by the initial load has only a name (and a reachability score when the workbook gives one) until it is completed in the storage structure (Phase 1b)
- **LocationRule**: id, target (`artist_id`, `alias_group_id`, `cluster_id`, **or `album_id`**), mandatory cabinet_id, note — always created manually. The `album_id` level is a specific-title exception: it detaches one release from its artist's normal placement (breaking the "artist stays together" rule in Sorting logic §1) without affecting the rest of that artist's catalog — needed for cases like a single boxset or compilation that lives in external storage while the rest of the artist stays in the main cabinet

**Placement**

- **Placement**: unit (`artist_id` — including an alias-group member —, `era_band_id`, or `album_id`), shelf_id, order position within the shelf, source (algorithm proposal, manually overridden, or initial load) — this is the one, canonical location; an album/artist has exactly one Placement, consuming shelf width (see Sorting logic §3). The most specific unit wins: an album's location is its own Placement if it has one (album-level location rule or manual move), otherwise that of its EraBand, otherwise that of its artist. Placing per era band is what lets one artist continue onto the next shelf at a band boundary, and what the Layout screen shows and drags (artist / era band)
- **ShowcaseFeature**: shelf_id (must reference a shelf with `is_showcase = true`), album_id or artist_id currently featured there. This is a **pointer to an existing Placement, not a placement of its own** — a showcase slot shows a sample "borrowed" from wherever that artist/album's real Placement already is, so it consumes no shelf width and isn't counted in any cabinet's capacity twice

## Architecture, storage, and deployment

### Layers (separation of concerns)

1. **Ingestion**: a spreadsheet loader for the initial load (Phase 1a — see [Initial load](#initial-load)), a CSV parser (detects vinyl by parsing the `Format` field) and a Discogs API client (fetches styles + original release year per release/master, used for import-time enrichment from Phase 1 onward, and for ongoing sync from Phase 2) — all produce the same internal Album/Artist structure
2. **Domain**: the entities above, as plain domain objects, independent of storage
3. **Sorting engine**: pure logic in small, self-contained steps (determining dominant cluster, co-occurrence clustering, computing era bands, placement/width allocation) — operates on domain objects, with no knowledge of the database or web layer
4. **Persistence**: storage of all entities, independent of the sorting engine
5. **Web**: Flask routes/blueprints + Bootstrap/JS templates, including the onboarding wizard. Light/dark theming uses Bootstrap 5.3's built-in `data-bs-theme` attribute rather than a custom theming layer — the toggle just switches that attribute and writes the choice to browser-local storage. UI copy goes through Flask-Babel (`gettext`/`_()`) from the start, with only an `en` catalog shipped in the MVP — this is the i18n-readiness the Language requirement calls for: adding a second language later means adding a `.po` catalog, not restructuring templates
6. **Confirmation layer**: a separate piece of logic that tracks proposals requiring confirmation (new style assignment, new location rule)

### Storage: files (JSON/CSV), no database

**Master data** (overwritable, no history needed):

- `artists.json`, `alias_groups.json`, `albums.json`, `styles.json`, `clusters.json`, `cabinets.json`, `shelves.json`, `location_rules.json`, `cluster_assignments.json` (the ArtistClusterAssignments), `era_bands.json`, `discogs_cache.json` (release/master enrichment cache — see Data model)

**Layout with history**:

- `placement_current.json` — active working state, overwritten on every change, no history
- `placements/` — directory of full snapshots, only created when the user explicitly chooses to "save this layout"; every snapshot is kept forever (no limit, no cleanup)

### DuckDB as the read/write layer

- The persistence layer uses DuckDB (`read_json_auto()` / `COPY ... TO '...json'`) to read and write the JSON files via SQL, instead of Python's `json` module — queries, joins, and aggregations (e.g. dominant-style determination, style co-occurrence, era-band spread) run as SQL against the JSON files
- DuckDB operates directly on the plain JSON files; there is no separate `.duckdb` database file
- Each file is a JSON array with one object per line, written with an explicit column schema per entity — readable and diffable by hand. Saving an entity rewrites its whole file (written to a temporary file first, then swapped in)
- **Explicitly out of scope**: Parquet and Delta Lake. At this scale (a single user, a personal collection, a handful of saved layouts) their benefit — avoiding full-copy storage across many versions — doesn't apply, while their cost (binary, non-diffable files; extra complexity) works directly against the project's goal of keeping the data human-readable and inspectable. The full-JSON-snapshot-per-save approach stays as is

### Configuration

- `config.yaml`, read and written with plain PyYAML — not through the DuckDB layer above, since this is scalar application settings, not queryable collection data
- Holds:
  - The width-estimation constants (base width, 180-gram surcharge, gatefold surcharge — see Sorting logic §3)
  - The Discogs personal access token
  - `count_bonus_discs_as_vinyl` (bool, default `true`) — whether a "bonus disc" bundle such as `"CD + LP"` is treated as vinyl during import (see Phase 1); defaults to the current any-segment-matches behavior, but is a setting rather than a hardcoded rule, since it's genuinely a judgment call
- Editable from a dedicated **Settings** screen in the web app (see UI), in addition to being written once by the onboarding wizard (Phase 1b, Discogs API enrichment step) when the token is first configured
- **Never committed to version control** — `config.yaml` is git-ignored, since it holds a credential. The Settings screen shows the API token masked (last 4 characters only), with a "replace" action rather than displaying it in full

### Deployment

- Self-hosted, deployed via Docker containers
- File storage (JSON) mounted as a volume, so data persists outside the container

## Onboarding wizard

Two strictly linear flows, matching the two steps of Phase 1. Once a flow is completed, the screens it unlocks are freely navigable.

### First use (Phase 1a)

1. **Welcome/intro**
2. **Initial load** — explanation of the expected workbook (sheets and columns), upload, then a preview: the locations and shelves found, record counts per shelf, and the number of unplaced albums (see [Initial load](#initial-load)); nothing needs to be configured
3. **Done** — the layout is written to `placement_current.json` and saved as the first version in `placements/`; the app opens on Browse/Search

### Sorting setup (Phase 1b)

Started from the regular app once the user wants a generated layout. A user without a spreadsheet goes straight from the welcome step into this flow.

1. **Storage structure** — cabinets + shelves (type, layer, width, reachability, showcase flag). After an initial load these already exist and only need reviewing and completing; otherwise they are created here
2. **Import collection** — explanation of the Discogs CSV export, upload, automatic filtering to vinyl (by parsing the `Format` field), preview of counts
3. **Discogs API enrichment** — personal access token setup, then fetch styles and original release years for every vinyl release (release → master lookups), with progress shown; safe to resume thanks to local caching
4. **Match loaded albums** (only after an initial load) — the albums from the spreadsheet are matched to the imported Discogs releases; uncertain matches are listed for confirmation (see [Initial load](#initial-load))
5. **Alias/project groups** (optional, may be left empty)
6. **Location rules** (optional, may be left empty)
7. **First sorting proposal** — all style assignments are bulk-accepted, the full proposal (including placement) is shown immediately, individually correctable. After an initial load this is optional: the loaded layout stays in place until the user chooses to replace it with a proposal
8. **Save** — explicit action; the version lands in `placements/`

## Initial load

The first thing a new installation does (Phase 1a): seed the collection and its layout directly from a spreadsheet the user has already worked out elsewhere, so the app is browsable without any Discogs data. This is a one-time bootstrap, not a permanent alternative to the sorting engine — a later re-sort (Phase 1b) can still produce a different result.

- **Input**: an XLSX workbook in the shape of `docs/import_example.xlsx`, with Dutch sheet and column names. It is the only source in Phase 1a — no Discogs export and no API access needed. Three sheets are read; any other sheet (e.g. `Toelichting`) is ignored:
  - `Kastindeling` (required) — one row per album-copy. Required columns: `Locatie`, `Vak`, `Cluster`, `Era-band (artiest)`, `Artiest`, `Titel`. Optional, used when present: `Formaat`, `Aantal schijven`, `Sorteerjaar (origineel)`. All other columns are ignored (`Inhoud van dit vak`, `Capaciteit`, `Jaar artiest`, `Label`, `Jaar (Discogs)`, `Jaarbron`, `Breedte-eenheden`, `Opmerking`)
  - `Vakoverzicht` (optional) — one row per shelf: `Locatie`, `Vak`, and `Toegankelijkheid`. Lists every shelf, including empty ones
  - `Nog niet geplaatst` (optional) — albums without a spot: `Cluster`, `Artiest`, `Titel`, `Aantal schijven`
  - A missing required sheet or column stops the upload with a message naming what is missing
- **Re-upload replaces everything**: in Phase 1a a new upload discards all previously loaded data and loads the workbook afresh — there is no merging. Saved versions in `placements/` are discarded too, since they refer to albums that no longer exist; the fresh load is saved as the new first version. Correcting the layout means correcting the workbook and uploading it again
- **Artists and albums**: each distinct `Artiest` value becomes an Artist, each row an Album — two rows with the same artist and title are two copies, so two Albums. From the row the Album also takes its `format_tokens` (`Formaat` plus `Aantal schijven`) and its original release year (`Sorteerjaar (origineel)`; `0` means unknown). `release_id`, styles, and width stay empty until the Discogs matching below
- **Cabinet/Shelf creation**: each distinct `Locatie` becomes a Cabinet, each (`Locatie`, `Vak`) pair a Shelf named after `Vak`, in the order of `Vakoverzicht` (then any pair that only occurs in `Kastindeling`). The reachability score is the leading number of `Toegankelijkheid`. Room, shelf type, layer, and width in cm are not in the workbook and stay empty until completed in the storage-structure step of Phase 1b. `Capaciteit` is not loaded: it counts LP-units rather than cm, and in the example it is derived from the contents rather than measured (see Open questions)
- **Placement**: each `Kastindeling` row becomes an album-level Placement on its shelf (source "initial load"), with the row order within a shelf as the position — the loaded layout mirrors the workbook exactly, which is what Browse/Search then follows
- **Matching to enriched Discogs data (Phase 1b)**: the spreadsheet has no `release_id`. Once the Discogs export has been imported and enriched, each loaded album is matched on (Artist, Title) by fuzzy string matching against the imported releases, to pull in `release_id`, styles, original year, and width. Matches below a confidence threshold are queued for manual confirmation rather than guessed — same non-blocking pattern as other confirmations (see Sorting logic §4): the album stays loaded and browsable, with the uncertain match flagged
- **Topladers are ordinary locations**: in the workbook an album sits in exactly one place — the rows under `Topladers` do not also appear on another shelf — so they are loaded as normal Placements, not as a `ShowcaseFeature`. Showcase features (a sample borrowed from a Placement elsewhere, see Data model) only come into play with showcase management in Phase 2
- **The Cluster column seeds the `Cluster` entity directly** (see Data model) — each distinct value becomes a Cluster, and each artist gets a confirmed `ArtistClusterAssignment` to the Cluster of its rows (the most frequent one if they differ). Once the albums are matched to Discogs in Phase 1b, their Styles are mapped to these Clusters instead of each getting a new same-named one. This is a natural fit: the spreadsheet's curated cluster names are exactly what the Clusters screen (see UI) lets the user build by hand later — initial load just bootstraps it from work already done
- **The Era band column is stored as the initial per-artist era-band label** — each distinct (Artist, Era band) value becomes an `EraBand` with source "initial load" (see Data model), and the row's album is linked to it. It doesn't have to match what the sorting engine's own logic (Sorting logic §2) would currently produce (e.g. this data uses decade labels like "1990s" rather than computed early/middle/late bands); re-running the proposal generator later is expected to diverge from this snapshot
- **Unplaced albums**: the rows of the `Nog niet geplaatst` sheet are loaded as Albums without a Placement — visible in a dedicated list, not silently dropped, so they can be resolved later (mark as external, free up shelf space, etc.). Locations such as `Overflow` or a not-yet-bought `Nieuwe koffer` are named in `Kastindeling` and are therefore loaded as ordinary Cabinets, exactly as the workbook has them

## UI / screen layout

### Main navigation (after the wizard)

Phase 1a ships only **Browse/Search** and **Unplaced albums**; the other items arrive with Phase 1b unless marked otherwise.

- **Dashboard** — overview: number of records, cabinets/shelves, last saved version
- **Layout** — core screen (see below)
- **Browse/Search** — crate-digging view of the collection, following the actual physical shelf order; search by artist and album (see Phase 1). This supersedes the earlier decision to have no separate "Collection" nav item — that assumption no longer holds now that browsing/search is its own dedicated feature, not just a detail drill-down from Layout
- **Storage structure** — manage cabinets/shelves
- **Alias groups** — management screen
- **Clusters** — rename a cluster, or merge several Styles into one cluster (see Sorting logic §1 and Data model); not part of the wizard — Clusters start out 1:1 with Styles and work unmodified, curation happens here at the user's own pace
- **Location rules** — management screen
- **Showcase** — manage top-loaders/samples (phase 2)
- **Versions** — saved layouts, with the option to restore
- **Settings** — edit `config.yaml`: width-estimation constants and the Discogs API token (masked, with a replace action)
- **Unplaced albums** — surfaces albums that don't fit anywhere in the current storage structure (see Initial load), so they can be resolved rather than silently dropped

Album/artist detail is still reachable both from Layout (clicking an artist/era band) and from Browse/Search.

### Layout screen (core)

- One tab/dropdown per location (room); within a location, all cabinets in that room are stacked underneath one another
- Each cabinet shows its shelves, with a filled bar visualizing the occupied width
- Plain text in phase 1 (artist, era band, record count); album covers are only added in phase 2 (affects display only, not the data model)
- Drag-and-drop (e.g. via SortableJS) between or within shelves adjusts order/placement
- Clickable through to album/artist detail from an artist/era band

### Browse/Search screen

- Crate-digging mode: renders the collection in physical order (cabinet → shelf → position within shelf), based on the current `Placement` data — scrolling through it mirrors flipping through the real shelves
- One shelf at a time, with previous/next shelf and a shelf picker to jump straight to any shelf. Within a shelf the albums are grouped under a heading per cluster and era band (the artist's dominant cluster), each row showing artist, title, and original year
- Search bar filtering by artist or album title (Phase 1); song-level search added once tracklist data is fetched (Phase 3). Every word typed must occur in the artist or title; case and accents are ignored. A result links to its shelf with the album marked — the Detail screen it will eventually open arrives in Phase 1b
- Plain text in Phase 1, same as Layout — covers follow the same phase-2 timeline
- **Mobile is the priority form factor for this screen** in particular — realistically used standing in front of the shelves: single-column layout, touch targets sized for tapping (prev/next shelf, search field), and the search bar / breadcrumb stay reachable without scrolling back up (e.g. sticky positioning)

### Clusters screen

- A searchable list of all Clusters, sorted by album count (descending) by default — makes both the big, already-meaningful clusters and the small single-style ones (the easiest merge candidates) easy to spot
- Each row shows: Cluster name, the Style(s) currently mapped to it (as chips), and counts (artists, albums)
- **Merging**: select 2+ clusters via checkboxes → a contextual "Merge N clusters" action appears → a dialog lets you pick which existing name to keep (defaulting to the one with the most albums) or type a new name, with a preview of the combined style/artist/album counts → confirming repoints every affected Style's `cluster_id` to the surviving cluster and removes the merged-away cluster rows. Any artist assignment (confirmed or not) pointing at a merged-away cluster is repointed automatically — this doesn't go through the new-shift confirmation flow (Sorting logic §4), since merging is itself the user's confirmed action
- **Un-merging / fine-tuning**: expanding a cluster row shows its member Styles individually, each with a "Move to cluster&hellip;" action (move to an existing cluster, or remove it to re-form its own standalone cluster) — this is how a Style gets taken back out of a merge, so no separate undo mechanism is needed
- **Renaming**: inline, on any cluster row, independent of merging
- Purely a taxonomy action — it relabels/regroups Styles and Clusters, but does not itself move any physical Placement. Regenerating a sorting proposal is what applies the new grouping to the actual layout

### Detail screen (artist/album)

- Reachable from both Layout and Browse/Search (clicking an artist/era band or a search result)
- Shows the dominant cluster with its confirmation status, and an action to correct it
- Shows an active location rule for the artist/alias group, if any
- Shows each era band's albums (title, original release year, current shelf)
- **Width confirmation action**: for an album with `manual_width_cm` unset (compound/box format — see Sorting logic §3), the screen surfaces the fallback estimate and lets the user enter the real width by hand. This is the actual place the "Openstaande bevestigingen" width flag (Dashboard) resolves to — Settings only holds the global constants, not per-album overrides
- Action to move the album/artist to a different shelf

## Open questions

- **Vinyl detection edge case**: whether a "bonus disc" bundle (e.g. `"CD + LP"`) counts as vinyl is now a configurable setting (`count_bonus_discs_as_vinyl`, default `true` — see Configuration) rather than a fixed rule, so this no longer needs to be settled up front
- **Width-estimation constants**: the 0.5 cm base / +0.15 cm (180g) / +0.2 cm (gatefold) figures (see Sorting logic §3) are an untested starting assumption, now configurable in `config.yaml` — to be tuned against real shelf measurements

### Parked after the Phase 1a initial load

Not blocking Phase 1a; set aside to be addressed later.

- **`Overflow` and `Nieuwe koffer` locations**: the workbook lists these under `Kastindeling`, so they are loaded as ordinary Cabinets and show up as locations in Browse/Search. Neither is a real, existing storage spot (overflow is a proposal to give away, the cases are yet to be bought) — whether they should appear in the Unplaced albums list instead is undecided
- **Shelf capacity after an initial load**: the workbook's `Capaciteit` and `Breedte-eenheden` count LP-units (1 for a single LP, 1.4 for a double), not cm, and are not loaded. Shelf widths in cm therefore have to be measured and entered in Phase 1b — or the app should learn to work in LP-units instead. Not needed for Browse/Search
- **Initial-load `Jaar artiest` column**: not loaded. It is the key the workbook was sorted on within an era band, and it is not strictly per artist (in the example five artists have two different values). The row order already preserves the resulting sequence; whether the value itself is worth keeping is undecided
