# Requirements — Sleeve & Shelf

*As of: October 9, 2026*

**Sleeve & Shelf** is a self-hosted, open-source Python Flask web application (Bootstrap + JavaScript) that organizes a vinyl collection (~1,190 vinyl titles out of ~1,455 tracked releases on Discogs) across a record cabinet, based on musical kinship, artist era, and physical shelf space.

> The Discogs collection CSV export contains no style/genre data and no original-release-year data (see [Sorting logic](#sorting-logic) and [Data model](#data-model)) — both are fetched from the Discogs API during import. Confirmed against a real export on 2026-09-20.

## Goal, scope, and phasing

### Phase 1 — MVP

The MVP is delivered in two steps. The record cabinet has already been laid out by hand, so the first need is to get that existing layout into the app and browse it (1a); having the app generate and maintain a layout itself comes second (1b).

#### Phase 1a — Import & Browse

- **Initial load**: seed the collection and its layout from an already-worked-out XLSX workbook (example: `docs/import_example.xlsx`) — see [Initial load](#initial-load). This is the only import in 1a: no Discogs CSV, no Discogs API, no access token. Uploading again later only changes the layout
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
- No album covers in Phase 1 — the standard Discogs CSV export does not include cover URLs, and cover art is out of scope for the Phase 1 API enrichment (built in Phase 2, see below)

### Phase 2 — Ongoing management

- **Live/ongoing** Discogs API integration: the one-time enrichment already happens in Phase 1 — Phase 2 extends this to keep the collection in sync (new purchases, changed collection data) rather than only at first import
  - **Built: sync on demand.** The collection is fetched straight from the Discogs API (the collection of the token's owner, 100 releases per request) and taken over exactly like a CSV export: same vinyl detection, same linking, same preview before anything changes (see Discogs screen). New vinyl becomes new, unplaced albums; albums whose release is no longer in the Discogs collection are marked and reported, and kept until the user removes them, which always takes a confirmation
  - **A sync brings the format of linked albums up to date** (decided 2026-10-09): disc count, 180 gram, gatefold and the other tokens are taken from the release, and the estimated width follows. A width measured by hand is not touched. An uploaded export does not do this — it knows the format less well than the API (see Discogs screen)
  - **A sync runs on demand only** (decided 2026-10-09): by the button on the Discogs screen, for now; not at start-up or on a schedule
- Add album covers to the Layout screen (Album gets a cover_url field)
  - **Built** (2026-10-09), and wider than Layout: covers also show in Browse/Search, in the Unplaced albums list, and on an artist's page. A sync stores the address of each release's small cover image on the album (`cover_url`); an uploaded export has no covers and leaves them alone. The images are not downloaded: the browser fetches them from Discogs when a page is shown, so covers need an internet connection while everything else keeps working without (see Open questions)
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
- **Installable (PWA)**: the app has a web app manifest and icons, so it can be put on the home screen of a phone and then opens as an app of its own, without the browser's address bar, on Browse/Search. Browsers only offer this over HTTPS (or on `localhost`); HTTPS is arranged outside the app, for instance by Tailscale or a reverse proxy. There is no service worker and no offline use: every page comes from the server
- **Language**: English is the primary and only shipped language for the MVP. Multi-language support is not needed now but is a real option for a later phase, so the MVP is built i18n-ready from the start (see Architecture) rather than retrofitted later. Discogs data itself (styles, genres) stays in English regardless of UI locale — that's external source data, not app copy, and isn't part of this requirement

## Sorting logic

### 1. Clustering by musical kinship (cluster)

This section and §2 follow the logic of the layout the collection is actually sorted by — the workbook behind the initial load (see [Initial load](#initial-load)). It replaces the earlier design, in which Discogs styles defined the clusters and each artist got its own early/middle/late bands.

- A **Cluster** is a curated group of artists that belong together by sound (e.g. "Jazz: Hard Bop", "Slowcore / Lo-fi Indiefolk") — not a Discogs style. Clusters are named and maintained by the user, via the Clusters screen (see UI)
- **Each artist belongs to exactly one Cluster** (`ArtistClusterAssignment`, see Data model). The assignments seeded by the initial load count as confirmed
- An artist whose catalogue spans too much to share a cluster forms **a cluster of its own** (in the example: Tom Waits, Nick Cave)
- **Artist families stay together**: an artist's other billings and side projects (e.g. "Chet Baker", "Chet Baker Quartet", and "Chet Baker & Crew"; "Nick Cave & The Bad Seeds" and "Grinderman") stand next to each other as one unit, in one cluster — the cluster most of the family's albums were curated into. A family is an alias group (see Data model). The app **suggests** families from the artist names — an artist whose name appears inside the names of others gathers them, and an artist naming several others goes to the one named first — and the user accepts a suggestion (optionally leaving members out) or turns it down for good. Families that names cannot reveal are added by hand (see Alias groups screen)
- **Discogs styles propose, they do not define.** Style tags are not in the Discogs CSV export — they are fetched per release from the Discogs API (see Phase 1b). Each Style is mapped to the Cluster that most of the artists carrying it were curated into; a Style none of them carries starts as a Cluster of its own, named after it. For an artist without a cluster (a new purchase), the Cluster most of its albums' Styles point to is proposed — in case of a tie the Cluster of the earliest album — and stays a proposal until confirmed (see §4)
- An artist always stays together as a whole — never split across clusters — **except** via an explicit album-level location rule (see Data model), which detaches one specific title without affecting the rest of the artist's catalog
- **Clusters stand in a curated order**, not a computed one: related clusters follow each other across the shelves (e.g. the Jazz clusters, the Singer-Songwriter clusters). The order is stored as a position on each Cluster. After an initial load it is read off the loaded layout — each cluster counts where its longest unbroken run of albums starts, so a few albums sampled on a showcase shelf or kept in external storage don't move it. A cluster that appears later (e.g. from a new Style) is added at the end
- **Singles and EPs stay outside the layout.** Only LPs are sorted and placed: an album takes part when its format contains an LP (`LP`, `2xLP`, …). 7", 10" and 12" releases are imported and listed, but never proposed a spot — except those that already stand in the current layout, which keep taking part

### 2. Era bands and the order within a cluster

- **Original release year.** The CSV's `Released` field is the year of the specific pressing owned, not the original release year (confirmed example: the 1980 reissue of David Bowie's *Space Oddity*, originally released 1969, is listed as `1980` in the export). The original release year is fetched via the Discogs API: release → `master_id` → master's year; a release without a master is its own only version, so its year is the original
- **A confirmed year is never overwritten.** A year that was looked up or corrected by hand (in the workbook: every `Jaarbron` other than "Discogs-jaar …" and "Onbekend") is marked confirmed on the album and survives enrichment; an unconfirmed year is replaced by the master's year
- **Artist start year**: the year the artist began (`Artist.start_year`), taken from the workbook's `Jaar artiest` (the lowest value when the rows differ). Discogs does not supply it; for an artist that is not in the workbook, the earliest original year among its own albums is the starting value. The user can always overwrite it, and is offered a link to look the artist up (Wikipedia) to verify. A family takes the earliest start year among its members
- **Era bands are fixed decades of the artist's start year**: before 1960, 1960s, 1970s, 1980s, 1990s, 2000s, 2010s, 2020s and later, and unknown. An artist's whole catalogue sits in the artist's band, so reissues and late albums don't scatter an artist over the cluster
- **Order within a cluster**: by era band, oldest first and unknown last → within a band by unit (a family, or an artist on its own), alphabetically by name as written (so "The Stooges" sorts under T) → within a unit by original release year, unknown last → by title
- **The workbook's 20-year rule is not applied.** The workbook's notes describe letting an album's own year decide its band when that year looks reliable and lies within 20 years of the artist's start. Applied literally to this collection it would scatter 389 albums of 250 artists over other bands than their artist's (Tom Waits over the 1970s and 1980s, for instance) — against both the rule above that an artist's catalogue stays in one band and the workbook's own layout, where all but two artists have a single band. For an artist without a known start year the albums already decide, through the earliest original year

### 3. Physical placement

- Shelf width in cm determines how many records fit. After an initial load the width is an **estimate**: the workbook's capacity in LP-units × the base width per disc (see below) — to be corrected per shelf once measured
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
- A cluster may span adjacent shelves within the same cabinet if it doesn't fit on one shelf
- **What does not fit is not forced in.** Albums a proposal has no room for are left unplaced: they appear in the Unplaced albums list, and the proposal states how many there are
- **The shelves are filled as one continuous row.** The albums, in the order of §1 and §2, are stood on the shelves in the order set under Storage: each shelf is filled until the next album no longer fits, and the row continues on the next shelf that has room — so a cluster, and an artist, can run on across shelves. A shelf once passed is not gone back to
- **Shelves a proposal skips**: a showcase shelf (it shows samples, see Data model) and a shelf without a width. An album whose format is unknown is taken to be one disc of base width
- **Location rules** bind a cluster, a family, an artist, or a single album to a cabinet (see Data model). A proposal places what a rule binds in that cabinet and nowhere else — bound albums that don't fit there are left out rather than put elsewhere — and a cabinet that rules send albums to holds only those albums: everything without a rule runs over the other cabinets. The most specific rule wins: an album's own, then its artist's, its family's, its cluster's
- Reachability only plays a role through the explicit, manually configured location rules — not as a general rule for popular/frequently-picked artists

### 4. Stability and confirmation

- Any shift of an artist to a different cluster (triggered by new purchases) is always presented for confirmation first — never applied silently
- The same applies to suggested new location rules: always requiring confirmation, never automatic
- **A generated proposal never replaces the current layout by itself.** It is kept next to the current layout (`placement_proposal.json`) until the user accepts it; until then Browse/Search keeps following the current layout, and discarding the proposal leaves everything as it was. Accepting makes it the current layout, saves that as a new version, records the cluster the engine proposed for artists without a confirmed one (as unconfirmed), and renews the era bands to match the sorting
- **Exception during first-time setup (wizard)**: for the very first layout of the full collection, all cluster assignments are automatically bulk-accepted (individually confirming them all isn't workable); the user corrects individual ones afterward as needed

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
    Album ||--o| MatchProposal : "proposed for"

    Artist {
        int id PK
        string name
        int discogs_artist_id "optional"
        int alias_group_id FK "nullable"
        int start_year "nullable"
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
        string cover_url "small cover image at Discogs, set by a sync"
        bool original_year_confirmed
        bool left_discogs "release no longer in the Discogs collection"
    }
    Style {
        int id PK
        string name "from Discogs"
        int cluster_id FK
    }
    Cluster {
        int id PK
        string name
        int position "place in the cluster sequence"
    }
    ArtistClusterAssignment {
        int artist_id PK, FK
        int cluster_id FK "null = artist is its own standalone cluster"
        bool confirmed
    }
    EraBand {
        int id PK
        int artist_id FK
        string label "decade band"
        int position "order within the artist"
        string source "algorithm or initial load"
    }
    Cabinet {
        int id PK
        string name
        string location "room, nullable"
        int position "order of the cabinets"
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
        int position "order within the cabinet"
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
        int year
        datetime fetched_at
    }
    MatchProposal {
        int album_id FK
        int release_id
        string artist
        string title
        float score
    }
    MasterEnrichment {
        int master_id PK
        int original_release_year
        datetime fetched_at
    }
```

**Core entities**

- **Artist**: id, name, Discogs artist ID (optional), alias_group_id (nullable), `start_year` (nullable — the year the artist began, which decides its era band; see Sorting logic §2)
- **AliasGroup**: id, label — an artist family: the Artists pointing at it stand together as one unit (see Sorting logic §1)
- **FamilyDismissal**: anchor artist id — a suggested family the user turned down, so it is not suggested again
- **Album**: id, artist_id, title, Discogs `release_id` (from CSV; nullable — an album seeded by the initial load has only artist and title until it is matched to Discogs in Phase 1b, and the same holds for its `format_tokens` and computed width), Discogs `master_id` (fetched), original release year (fetched via master), `format_tokens` (parsed from the CSV `Format` field — disc count, 180-gram, gatefold, compound/`Box` flag, and other qualifiers), computed width (cm, derived from `format_tokens` for simple formats — see Sorting logic §3), `manual_width_cm` (nullable — set by hand for compound/box formats, overrides the computed value when present), `width_confirmed` (bool — false for compound formats until manually set), list of styles (fetched via release), `era_band_id` (nullable — the EraBand this album falls in, see Sorting/clustering below; empty until a proposal is generated or an initial load is done), `cover_url` (the address of the release's small cover image at Discogs, set by a sync; empty until the first sync), `original_year_confirmed` (bool — true when the year is known to be the original rather than a pressing's, so enrichment leaves it alone; see Sorting logic §2), `left_discogs` (bool — true when the last sync or import no longer found the album's release in the Discogs collection; set again at every sync or import)
- **Style**: id, name (from Discogs), `cluster_id` — the Cluster this Style points to; set the first time the Style is seen, user-remappable afterward (see Sorting logic §1)
- **Cluster**: id, name — a user-curated group of artists, decoupled from Discogs' own style taxonomy (see Sorting logic §1); seeded by the initial load, can be renamed or merged via the Clusters screen (see UI). `position` is its place in the curated sequence of clusters

**Discogs enrichment cache** (avoids re-fetching on every import/wizard run)

- **ReleaseEnrichment**: release_id, styles, master_id, year (the release's own year — the original year when there is no master), fetched_at
- **MasterEnrichment**: master_id, original_release_year, fetched_at
- **MatchProposal**: album_id, release_id, artist and title of that release, score — an uncertain link between a loaded album and a Discogs release, waiting for confirmation (see [Initial load](#initial-load)); not a cache record, but it lives alongside them

**Sorting/clustering**

- **ArtistClusterAssignment**: artist_id, cluster_id (the artist's cluster — curated, or proposed from its albums' Styles; or a standalone cluster pointing at the artist itself), confirmed (bool) — distinguishes a proposed dominant cluster from a confirmed one
- **EraBand**: id, artist_id, label, position (order of the band within the artist's timeline), source (algorithm vs. initial load) — one band of an artist's discography (see Sorting logic §2); albums point at their band via `era_band_id`. The label is the decade band (e.g. "1990s" — see Sorting logic §2); an initial load stores the workbook's own labels as-is. Era bands are persisted, so the bands seeded by an initial load are kept until a proposal is accepted
- **ClusterOrder**: the curated sequence of the clusters (see Sorting logic §1) — not an entity of its own: it is the `position` of each Cluster

**Storage structure**

- **Cabinet**: id, name, location (room; nullable — not known after an initial load), `position` (its place in the order the cabinets are walked)
- **Shelf**: id, cabinet_id, name (the label of the shelf within its cabinet, e.g. "a"), width (cm), type (top-/front-loader), layer, reachability score, is_showcase (bool). Width, type, layer, and reachability are nullable: a shelf seeded by the initial load has only a name (and a reachability score when the workbook gives one) until it is completed in the storage structure (Phase 1b). `position` is its place among the shelves of its cabinet
- **LocationRule**: id, target (`artist_id`, `alias_group_id`, `cluster_id`, **or `album_id`**), mandatory cabinet_id, note — always created manually. The `album_id` level is a specific-title exception: it detaches one release from its artist's normal placement (breaking the "artist stays together" rule in Sorting logic §1) without affecting the rest of that artist's catalog — needed for cases like a single boxset or compilation that lives in external storage while the rest of the artist stays in the main cabinet

**Placement**

- **Placement**: unit (`artist_id` — including an alias-group member —, `era_band_id`, or `album_id`), shelf_id, order position within the shelf, source (algorithm proposal, manually overridden, or initial load) — this is the one, canonical location; an album/artist has exactly one Placement, consuming shelf width (see Sorting logic §3). The most specific unit wins: an album's location is its own Placement if it has one (album-level location rule or manual move), otherwise that of its EraBand, otherwise that of its artist. Placing per era band is what lets one artist continue onto the next shelf at a band boundary, and what the Layout screen shows and drags (artist / era band)
- **ShowcaseFeature**: shelf_id (must reference a shelf with `is_showcase = true`), album_id or artist_id currently featured there. This is a **pointer to an existing Placement, not a placement of its own** — a showcase slot shows a sample "borrowed" from wherever that artist/album's real Placement already is, so it consumes no shelf width and isn't counted in any cabinet's capacity twice

## Architecture, storage, and deployment

### Layers (separation of concerns)

1. **Ingestion**: a spreadsheet loader for the initial load (Phase 1a — see [Initial load](#initial-load)), a CSV parser (detects vinyl by parsing the `Format` field) and a Discogs API client (fetches styles + original release year per release/master, used for import-time enrichment from Phase 1 onward, and for ongoing sync from Phase 2) — all produce the same internal Album/Artist structure
2. **Domain**: the entities above, as plain domain objects, independent of storage
3. **Sorting engine**: pure logic in small, self-contained steps (proposing a cluster for an artist, deriving era bands, ordering within a cluster, placement/width allocation) — operates on domain objects, with no knowledge of the database or web layer
4. **Persistence**: storage of all entities, independent of the sorting engine
5. **Web**: Flask routes/blueprints + Bootstrap/JS templates, including the onboarding wizard. Light/dark theming uses Bootstrap 5.3's built-in `data-bs-theme` attribute rather than a custom theming layer — the toggle just switches that attribute and writes the choice to browser-local storage. UI copy goes through Flask-Babel (`gettext`/`_()`) from the start, with only an `en` catalog shipped in the MVP — this is the i18n-readiness the Language requirement calls for: adding a second language later means adding a `.po` catalog, not restructuring templates. The catalogues live in `src/sleeve_shelf/translations/`: `messages.pot` is the template extracted from the code and templates (sources listed in `babel.cfg`), `en/LC_MESSAGES/messages.po` the English catalogue — left untranslated, since the copy in the code is already English. A test fails when the template no longer matches the copy in the code
6. **Confirmation layer**: a separate piece of logic that tracks proposals requiring confirmation (new style assignment, new location rule)

### Storage: files (JSON/CSV), no database

**Master data** (overwritable, no history needed):

- `artists.json`, `alias_groups.json`, `family_dismissals.json`, `albums.json`, `styles.json`, `clusters.json`, `cabinets.json`, `shelves.json`, `location_rules.json`, `cluster_assignments.json` (the ArtistClusterAssignments), `era_bands.json`, `discogs_releases.json` and `discogs_masters.json` (the enrichment cache — see Data model), `match_proposals.json`

**Layout with history**:

- `placement_current.json` — active working state, overwritten on every change, no history
- `placement_proposal.json` — a sorting proposal waiting for a decision; removed when it is accepted or discarded
- `placements/` — directory of full snapshots of the placement, one file per saved version, named by date and time and an optional label. Versions are saved when the user chooses to, and automatically at the moments listed under Versions screen; every snapshot is kept (no limit, no cleanup)

### DuckDB as the read/write layer

- The persistence layer uses DuckDB (`read_json_auto()` / `COPY ... TO '...json'`) to read and write the JSON files via SQL, instead of Python's `json` module — queries, joins, and aggregations (e.g. dominant-style determination, style co-occurrence, era-band spread) run as SQL against the JSON files
- DuckDB operates directly on the plain JSON files; there is no separate `.duckdb` database file
- Each file is a JSON array with one object per line, written with an explicit column schema per entity — readable and diffable by hand. Saving an entity rewrites its whole file (written to a temporary file first, then swapped in)
- **Explicitly out of scope**: Parquet and Delta Lake. At this scale (a single user, a personal collection, a handful of saved layouts) their benefit — avoiding full-copy storage across many versions — doesn't apply, while their cost (binary, non-diffable files; extra complexity) works directly against the project's goal of keeping the data human-readable and inspectable. The full-JSON-snapshot-per-save approach stays as is

### Configuration

- `config.yaml`, kept in the data directory next to the JSON files, read and written with plain PyYAML — not through the DuckDB layer above, since this is scalar application settings, not queryable collection data
- Holds:
  - The width-estimation constants (base width, 180-gram surcharge, gatefold surcharge — see Sorting logic §3); the base width also turns the workbook's LP-unit capacity into an estimated shelf width
  - The Discogs personal access token
  - `count_bonus_discs_as_vinyl` (bool, default `true`) — whether a "bonus disc" bundle such as `"CD + LP"` is treated as vinyl during import (see Phase 1); defaults to the current any-segment-matches behavior, but is a setting rather than a hardcoded rule, since it's genuinely a judgment call
- Editable from a dedicated **Settings** screen in the web app (see UI), in addition to being written once by the onboarding wizard (Phase 1b, Discogs API enrichment step) when the token is first configured
- **Never committed to version control** — `config.yaml` is git-ignored, since it holds a credential. The Settings screen shows the API token masked (last 4 characters only), with a "replace" action rather than displaying it in full

### Deployment

- Self-hosted, deployed via Docker containers
- File storage (JSON) mounted as a volume, so data persists outside the container: the image keeps all data in `/data` and listens on port 5000
- The image (`docker/Dockerfile`) is built and published (first built successfully from the `test` branch) to the GitHub Container Registry (`ghcr.io/mark-me/sleeve-shelf`) by a GitHub Actions workflow, which first runs the test suite:
  - push to `test` → `:test`, amd64 only (a quick build for trying things out)
  - push to `main` → `:main` and `:latest`, amd64 + arm64
  - a release tag `vX.Y.Z` on `main` → `:X.Y.Z`, amd64 + arm64
  - every image is also tagged with its short commit SHA
- The build stamps the image with a version, shown in the app's navigation: `X.Y.Z` for a release, `X.Y.Z+main.<commits since release>.<sha>` on `main`, `X.Y.Z+test.<sha>` on `test`

## Onboarding wizard

Two strictly linear flows, matching the two steps of Phase 1. Once a flow is completed, the screens it unlocks are freely navigable.

### First use (Phase 1a)

1. **Welcome/intro**
2. **Initial load** — explanation of the expected workbook (sheets and columns), upload, then a preview: the locations and shelves found, record counts per shelf, and the number of unplaced albums (see [Initial load](#initial-load)); nothing needs to be configured
3. **Done** — the layout is written to `placement_current.json` and saved as the first version in `placements/`; the app opens on Browse/Search

### Sorting setup (Phase 1b)

Started from the regular app once the user wants a generated layout. Steps 1–4 are not a locked sequence in the app: step 1 is the Storage screen and steps 2–4 are the three parts of the Discogs screen (see UI), each of which can be revisited. A user without a spreadsheet goes straight from the welcome step into this flow.

1. **Storage structure** — cabinets + shelves (type, layer, width, reachability, showcase flag). After an initial load these already exist and only need reviewing and completing; otherwise they are created here
2. **Import collection** — explanation of the Discogs CSV export, upload, automatic filtering to vinyl (by parsing the `Format` field), preview of counts
3. **Discogs API enrichment** — personal access token setup, then fetch styles and original release years for every vinyl release (release → master lookups), with progress shown; safe to resume thanks to local caching
4. **Match loaded albums** (only after an initial load) — the albums from the spreadsheet are matched to the imported Discogs releases; uncertain matches are listed for confirmation (see [Initial load](#initial-load))
5. **Alias/project groups** (optional, may be left empty)
6. **Location rules** (optional, may be left empty)
7. **First sorting proposal** — all cluster assignments are bulk-accepted, the full proposal (including placement) is shown immediately, individually correctable. After an initial load this is optional: the loaded layout stays in place until the user chooses to replace it with a proposal
8. **Save** — explicit action; the version lands in `placements/`

## Initial load

The first thing a new installation does (Phase 1a): seed the collection and its layout directly from a spreadsheet the user has already worked out elsewhere, so the app is browsable without any Discogs data. This is a one-time bootstrap, not a permanent alternative to the sorting engine — a later re-sort (Phase 1b) can still produce a different result.

- **Input**: an XLSX workbook in the shape of `docs/import_example.xlsx`, with Dutch sheet and column names. It is the only source in Phase 1a — no Discogs export and no API access needed. Three sheets are read; any other sheet (e.g. `Toelichting`) is ignored:
  - `Kastindeling` (required) — one row per album-copy. Required columns: `Locatie`, `Vak`, `Cluster`, `Era-band (artiest)`, `Artiest`, `Titel`. Optional, used when present: `Formaat`, `Aantal schijven`, `Sorteerjaar (origineel)`, `Jaarbron`, `Jaar artiest`, `Capaciteit`. All other columns are ignored (`Inhoud van dit vak`, `Label`, `Jaar (Discogs)`, `Breedte-eenheden`, `Opmerking`)
  - `Vakoverzicht` (optional) — one row per shelf: `Locatie`, `Vak`, `Capaciteit`, and `Toegankelijkheid`. Lists every shelf, including empty ones
  - `Nog niet geplaatst` (optional) — albums without a spot: `Cluster`, `Artiest`, `Titel`, `Aantal schijven`
  - A missing required sheet or column stops the upload with a message naming what is missing
- **A later upload only changes the layout.** The first upload loads everything. Once a collection exists, a new workbook is applied as a change of layout only: albums are recognised by artist and title (two pressings of one title by their format) and keep everything known about them — Discogs link, years, styles, family, cluster. Where they stand is taken from the workbook. Albums the workbook no longer lists are kept and become unplaced; albums, artists, cabinets, and shelves that are new are added, the new artists with the cluster, era band, and start year from their rows. Cabinets and shelves are recognised by name and keep what was filled in for them (width, type, row, reachability). Cluster assignments, the cluster order, and families are never changed by an upload. The result is saved as a new version in `placements/`; earlier versions stay valid
- **Artists and albums**: each distinct `Artiest` value becomes an Artist, each row an Album — two rows with the same artist and title are two copies, so two Albums. From the row the Album also takes its `format_tokens` (`Formaat` plus `Aantal schijven`) and its original release year (`Sorteerjaar (origineel)`; `0` means unknown), confirmed or not according to `Jaarbron` (see Sorting logic §2). Its width is estimated from the format right away (see Sorting logic §3). The Artist takes its start year from `Jaar artiest`. `release_id` and styles stay empty until the Discogs matching below
- **Cabinet/Shelf creation**: each distinct `Locatie` becomes a Cabinet, each (`Locatie`, `Vak`) pair a Shelf named after `Vak`, in the order of `Vakoverzicht` (then any pair that only occurs in `Kastindeling`). The reachability score is the leading number of `Toegankelijkheid`. The shelf width is estimated from `Capaciteit`, which counts LP-units rather than cm: units × the base width per disc from the settings (see Sorting logic §3). Room, shelf type, and layer are not in the workbook and stay empty until completed in the storage-structure step of Phase 1b
- **Placement**: each `Kastindeling` row becomes an album-level Placement on its shelf (source "initial load"), with the row order within a shelf as the position — the loaded layout mirrors the workbook exactly, which is what Browse/Search then follows
- **Matching to the Discogs export (Phase 1b)**: the spreadsheet has no `release_id`. Importing the Discogs export links each loaded album to the vinyl release with the same artist and title (ignoring case and spacing); two pressings of one title are told apart by their format. For an album left without a release, the most similar remaining release is only **proposed** (`MatchProposal`, see Data model) and has to be confirmed by hand — same non-blocking pattern as other confirmations (see Sorting logic §4): the album stays loaded and browsable. Vinyl releases in the export that no loaded album accounts for become new albums without a placement, visible under Unplaced albums. Non-vinyl releases are skipped. Importing the same export again changes nothing
- **Topladers are ordinary locations**: in the workbook an album sits in exactly one place — the rows under `Topladers` do not also appear on another shelf — so they are loaded as normal Placements, not as a `ShowcaseFeature`. Of the `Topladers` shelves only `a` and `b` are meant as rotating samples; `c` is an ordinary shelf. Showcase features (a sample borrowed from a Placement elsewhere, see Data model) only come into play with showcase management in Phase 2
- **The Cluster column seeds the `Cluster` entity directly** (see Data model) — each distinct value becomes a Cluster, and each artist gets a confirmed `ArtistClusterAssignment` to the Cluster of its rows (the most frequent one if they differ). Once the albums are matched to Discogs and enriched in Phase 1b, their Styles are mapped to these Clusters (see Sorting logic §1). This is a natural fit: the spreadsheet's curated cluster names are exactly what the Clusters screen (see UI) lets the user build by hand later — initial load just bootstraps it from work already done
- **The Era band column is stored as the initial per-artist era-band label** — each distinct (Artist, Era band) value becomes an `EraBand` with source "initial load" (see Data model), and the row's album is linked to it. The workbook's decade labels ("voor 1960", "1990s", …) are the same bands the sorting engine works with (see Sorting logic §2)
- **Unplaced albums**: the rows of the `Nog niet geplaatst` sheet are loaded as Albums without a Placement — visible in a dedicated list, not silently dropped, so they can be resolved later (mark as external, free up shelf space, etc.). Locations such as `Overflow` or a not-yet-bought `Nieuwe koffer` are named in `Kastindeling` and are therefore loaded as ordinary Cabinets, exactly as the workbook has them

## UI / screen layout

### Main navigation (after the wizard)

The menu is grouped in the order the app is used — what is done daily on top, what is rarely touched at the bottom. All items are built, except where a later phase is marked.

- **Dashboard** — overview and open confirmations (see below)
- **Collection**
  - **Browse / Search** — crate-digging view of the collection, following the actual physical shelf order; search by artist and album (see Phase 1)
  - **Unplaced albums** — albums without a spot on a shelf (see Initial load), so they can be resolved rather than silently dropped
- **Arrange**
  - **Layout** — core screen (see below)
  - **Sorting proposal** — generate a proposal, compare it with the current layout, accept or discard it (see below)
  - **Versions** — saved layouts, with the option to put one back (see below)
- **Sorting rules** — what decides how a proposal sorts, in the order they are best gone through
  - **Artists** — the list of artists, and per artist its start year and cluster (see below)
  - **Artist families** — the alias groups: accept or turn down suggested families, and manage them by hand (see below)
  - **Clusters** — the clusters in their order: reorder, rename, merge, and re-point styles (see below)
  - **Location rules** — bind a cluster, a family, an artist, or an album to a cabinet (see below)
- **Setup**
  - **Cabinets & shelves** — the Storage structure screen: manage cabinets and shelves
  - **Discogs sync** — the Discogs screen: sync or import the collection, fetch styles and original years, confirm proposed matches (see below)
  - **Import workbook** — load a layout workbook (see Initial load)
  - **Settings** — edit `config.yaml`: the width-estimation constants, whether a bonus-disc bundle counts as vinyl, and the Discogs API token (masked, with a replace action); see below
- **Showcase** — manage top-loaders/samples (phase 2, not in the menu yet)

**Counters in the menu**: an item shows a number when something there is waiting for the user — the same counts as the Dashboard's "Waiting for you": LPs without a place (Unplaced albums), artists without a confirmed cluster or start year (Artists), suggested families not yet looked at (Artist families), shelves filled beyond their width (Cabinets & shelves), and matches to confirm plus albums no longer in the Discogs collection (Discogs sync). An item with nothing waiting shows no number.

Album/artist detail is still reachable both from Layout (clicking an artist/era band) and from Browse/Search.

### Layout screen (core)

- All cabinets underneath one another, in the order set under Storage, each showing its shelves. A shelf has a bar for the occupied width, with the number of albums and the filled and total width; a shelf filled beyond its width is marked
- The contents of a shelf are **blocks**: neighbouring albums of one artist form one block, showing the artist and the number of albums (a single album shows its title). A block shows the cover of its first album; split into single albums, each shows its own
- **Drag and drop** (SortableJS) moves a block between or within shelves; every move is saved at once and the bars update. Clicking the number on a block splits it into single albums, so one album can be moved on its own. While dragging, the page scrolls along as soon as the pointer comes within some 160 px of the top or bottom of the window, so a block can be carried from the tray to a shelf far up the page
- **Not on a shelf**: a tray at the bottom holds the LPs without a place. Dragging from it places an album; dropping an album on it takes the album off its shelf
- **Which layout**: the screen adjusts the shelves as they are, or — when there is a proposal — the proposal, with a switch between the two. Adjusting the proposal changes nothing on the shelves until it is accepted; moved albums are marked as placed by hand
- A move that would lose or duplicate an album (the page being out of date, for instance) is refused and the screen asks to reload
- **One tab per room**: cabinets are grouped by the room set for them under Storage, one tab per room in the order the rooms first occur; cabinets without a room share a tab. With a single room there are no tabs. The tray of unplaced LPs is shown in every room
- The artist's name on a block opens that artist (see Artists screen)

### Dashboard

- The home screen once a collection is loaded: counters for the albums in the layout, how many stand on a shelf, artists, clusters, cabinets, and shelves; and how many singles and EPs are kept outside the layout
- **Waiting for you** (the open confirmations): Discogs matches to confirm, suggested artist families not yet looked at, artists sorted on a proposed cluster or a year taken from their albums, box sets and bundles with only a rough width, albums without a Discogs release, albums no longer in the Discogs collection, shelves filled beyond their width, and LPs without a place — each linking to the screen where it is resolved. Only what is not zero is shown
- **Towards a new layout**: the steps from collection to sorted layout as a numbered list, in the order of the menu, each linking to its screen — bring the collection up to date (Discogs sync), go through the suggested families, check the artists' clusters and start years, put the clusters in order, measure the shelves, pin what has to stand in a certain cabinet (optional), and generate, adjust and accept a proposal. A step that can be counted shows how much is left to do (matches to confirm and releases still to fetch; suggested families; artists to check; shelves without a width or filled beyond it) and is ticked off at zero; the others show what there is (number of clusters, number of rules, whether a proposal is waiting). No step is compulsory or locked
- Whether a proposal is waiting, and the last saved version with whether the layout has changed since

### Browse/Search screen

- Crate-digging mode: renders the collection in physical order (cabinet → shelf → position within shelf), based on the current `Placement` data — scrolling through it mirrors flipping through the real shelves
- One shelf at a time, with previous/next shelf and a shelf picker to jump straight to any shelf. Within a shelf the albums are grouped under a heading per cluster and era band (the artist's dominant cluster), each row showing artist, title, and original year
- Search bar filtering by artist or album title (Phase 1); song-level search added once tracklist data is fetched (Phase 3). Every word typed must occur in the artist or title; case and accents are ignored. A result links to its shelf with the album marked, or to the Unplaced albums list when it has no spot. The artist name on a shelf row opens that artist (see Artists screen)
- Each row shows the album's cover as a small square, on a shelf and in search results. An album without a cover keeps the space so the rows line up; while no album in the list has a cover (before the first sync) no space is kept at all
- **Mobile is the priority form factor for this screen** in particular — realistically used standing in front of the shelves: single-column layout, touch targets sized for tapping (prev/next shelf, search field), and the search bar / breadcrumb stay reachable without scrolling back up (e.g. sticky positioning)

### Discogs screen

One screen for the three Discogs steps of the sorting setup (see [Onboarding wizard](#onboarding-wizard)); each can be repeated at any time.

- **Counters** at the top: albums, albums linked to a release, albums enriched, and matches waiting for confirmation
- **Import your collection**, in two ways that do the same: **Sync with Discogs** fetches the collection through the API with the token set below (about a second per hundred releases; not while styles and years are being fetched, since both draw on the same rate limit), or upload the Discogs CSV export. Either way a preview follows of what it would do — vinyl releases found, linked to existing albums, proposed matches, new unplaced albums, non-vinyl skipped — and only then confirm. Syncing or importing the same collection again changes nothing
- **No longer in your Discogs collection**: the preview lists the albums whose release the collection no longer holds (sold or removed on Discogs). Once confirmed they are marked (`left_discogs`) and listed in a section of their own on this screen, each linking to its artist, and counted on the Dashboard. The albums stay as they are, on their shelf; a release that is back at the next sync loses the mark
- **Removing an album that left Discogs** (decided 2026-10-09): each album in that list has a Remove action, which first asks for confirmation on a page of its own, showing the album and where it stands. Only after confirming is the album removed — from the app, from its shelf (also in a waiting proposal), together with its own location rule and a proposed match. The layout as it was is saved as a version first; the artist stays, even without albums. Cancelling changes nothing, and there is no "keep and stop asking": an album that is not removed is listed again after every sync, for now. Only an album marked as gone can be removed this way
- **Linked albums**: the preview of a sync says how many linked albums get their format brought up to date; an uploaded export leaves linked albums as they are
- **Formats from the API**: the API spells a format out where the export abbreviates it, so a synced release gets the same tokens as an exported one (`Reissue` → `RE`, …). The export keeps only the first three letters of a format's free text ("Blue Translucent, Gatefold" → `Blu`); a sync searches that text for 180 gram and gatefold instead, so it recognises them where the export misses them
- **Fetch styles and original years**: the personal access token is set here (shown masked, last 4 characters, with a replace action — the same rule as on the Settings screen). The enrichment runs in the background of the app, not inside a page request: the page shows a progress bar that keeps itself up to date, and a Stop button. Stopping, an error, or a restart of the app loses nothing — starting again continues with what is not cached yet. Only one enrichment runs at a time
- **Matches to confirm**: each proposed match (see [Initial load](#initial-load)) shows the album and the Discogs release side by side, with their similarity. "Same album" links them; "Different" leaves the album without a release and adds the release as a new, unplaced album

### Sorting proposal screen

- **Before generating**: how many albums take part, how many shelves will be filled, and which shelves are skipped and why. If suggested artist families have not been looked at yet, the screen says so and links to them — families decide which artists stand together
- **Generate a proposal** sorts the collection and fills the shelves (see Sorting logic); it takes well under a second
- **The proposal**: counters for albums placed, albums that go to another shelf, albums that stay on their shelf, and albums that do not fit. Per cabinet a table of its shelves with width, filled width now and proposed, and number of albums now and proposed, each shelf linking to its proposed contents
- **Browse the proposal**: the proposal can be walked shelf by shelf exactly like the real shelves in Browse/Search, under a notice that it is the proposal; search stays on the current layout
- **Do not fit**: the albums no shelf had room for, marking those that stand on a shelf now
- **Accept**, **Generate again** (after changing families, clusters, storage, or widths), and **Discard**
- Adjusting the proposal by hand — moving albums between and within shelves — is done on the Layout screen, switched to the proposal (see Layout screen)

### Artists screen

- **List**: every artist with its cluster, start year, family, and number of albums; searchable by name. A cluster the app proposed is marked "proposed", a start year taken from the albums is marked "from albums"
- **To check**: a filter for the artists whose albums are sorted but that have no confirmed cluster or no start year of their own. A proposed cluster can be confirmed straight from the list
- **One artist**: the start year can be set or cleared — cleared, the earliest original year among the artist's albums is used again — with a link that looks the artist up on Wikipedia to verify it. The cluster is chosen from the existing clusters, or a new one is named (an artist's own cluster, for example); the screen also shows which cluster the Discogs styles of the albums point to. Saving a cluster confirms it; choosing none lets the app propose one again
- The page lists the artist's albums with year, format, and where each stands, and is reached from the artist name in Browse/Search. This is the artist half of the Detail screen described further down
- Like families and clusters, these are sorting inputs: they change the next proposal, not the current layout

### Settings screen

- **Album width**: base width per disc, extra per 180-gram disc, and extra for a gatefold sleeve (see Sorting logic §3). Saving recalculates the estimated width of every album; shelf widths are not touched — those are set per shelf under Storage
- **Room**: the screen shows how many cm the albums of a proposal need, how many the shelves it fills offer, and the difference — the quickest way to see whether the estimates add up
- **Discogs**: whether a bundle such as "CD + LP" counts as vinyl (applies at the next import), and the personal access token, shown masked

### Album widths screen

- **To measure**: the box sets and bundles (compound formats, see Sorting logic §3) that still count as loose discs, each with its format and the rough estimate, and a field to enter the real width in cm. This is where the Dashboard's width flag resolves to
- **Measured**: the albums with a width set by hand; a width can be changed, or cleared to go back to the estimate
- A measured width overrides the estimate everywhere — shelf fill, Layout, proposals — and is not touched when the width settings change. Reached from the Dashboard, the Storage screen, and an album marked "rough width" on its artist's page

### Alias groups screen (artist families)

- **Suggested from the names**: every suggestion shows the anchor artist and the artists whose names contain it, each with its number of albums and its cluster — so a member that sits in another cluster is visible before accepting. Each member has a checkbox, ticked by default; "Make this a family" creates the family from the anchor and the ticked members, "Not a family" removes the suggestion for good. "Accept all" takes every suggestion as it stands
- **Families**: each family shows its members; the name can be changed, members taken out, and artists added by name (from the artists that are not in a family yet). A family can be removed, after which its artists stand on their own again
- **Add family**: a new, empty family by name — for families the names don't reveal (e.g. Songs: Ohia and Magnolia Electric Co.)
- Like the Clusters screen this is taxonomy only: it changes how the next proposal is sorted, not where anything stands now

### Location rules screen

- **Add a rule**: choose what it is for (a cluster, a family, an artist, or one album), pick the name from the list, choose the cabinet, and optionally note why. A target has one rule: a new rule for the same target replaces the old
- **Rules**: each rule with its target, cabinet, and note, and a remove action. A rule whose target or cabinet no longer exists is shown as such
- Rules are sorting inputs: they take effect the next time a proposal is generated (see Sorting logic §3)

### Versions screen

- The saved versions, newest first, each with when it was saved, its name if it has one, and how many albums it places; the one that equals the current layout is marked
- **Save version**: the layout as it is now, optionally under a name
- **Put back**: makes a version the current layout. Only where albums stand changes; the layout as it was is saved first when it wasn't, so putting back can itself be undone. Albums or shelves of the version that no longer exist are left out, and the screen says how many
- Versions are also saved automatically: when a workbook is loaded, when a proposal is accepted (and the layout before it, if it had unsaved changes), and — at most once an hour — before the layout is changed by hand, so an editing session in Layout always starts from a version to go back to

### Storage structure screen

- Lists every cabinet (name and room) with its shelves: name, type, row, width, filled width, number of albums, reachability, and showcase flag
- Cabinets and shelves can be added and edited. A shelf is edited on its own page: name, width in cm, type (top-/front-loader), row (top/bottom), reachability (a whole number, 1 being the easiest to reach), and showcase — which only a top-loader can be. Type, row, width, and reachability may be left empty when not known yet
- **Filled width** is the summed width of the albums standing on the shelf; when it exceeds the shelf width it is marked. After an initial load the shelf widths are estimates (see Sorting logic §3), so this mark mostly says the estimate needs measuring
- A shelf can only be removed once it holds no albums, a cabinet once it has no shelves — nothing is ever unplaced as a side effect of tidying the structure
- **Order**: cabinets, and the shelves within a cabinet, stand in an order the user sets with up/down arrows. It is the order in which they are walked — by previous/next shelf in Browse/Search and by a sorting proposal, which fills the shelves in this order. Until moved, they keep the order they were added in; new cabinets and shelves are added at the end

### Clusters screen

- A list of all clusters **in their order across the shelves**, each with its number of artists (linking to those artists) and albums, and the Discogs styles that point at it. Up/down arrows change the order (see Sorting logic §1)
- **Merging**: tick two or more clusters and merge them. Their artists, styles, and location rules move into the cluster with the most albums, which keeps its place in the order — and its name, unless another is given. This doesn't go through the confirmation flow (Sorting logic §4), since merging is itself the user's confirmed action
- **One cluster**: rename it, and see the styles pointing at it — each can be pointed at another cluster, which changes what is proposed for new artists carrying that style. A cluster without artists, styles, and rules can be removed
- **Moving an artist to another cluster** is done on the artist (see Artists screen), where a new cluster can also be made
- Purely a taxonomy action — it does not itself move any physical Placement. Generating a sorting proposal is what applies the new grouping and order to the layout

### Detail screen (artist/album)

- Reachable from both Layout and Browse/Search (clicking an artist/era band or a search result)
- Shows the dominant cluster with its confirmation status, and an action to correct it
- Shows an active location rule for the artist/alias group, if any
- Shows each era band's albums (title, original release year, current shelf)
- **Width confirmation action**: entering the real width of a compound/box format is done on the Album widths screen (see above); Settings only holds the global constants, not per-album overrides
- Action to move the album/artist to a different shelf

## Open questions

- **Covers are fetched from Discogs by the browser**, not kept in the data directory. That was chosen without asking, as the smallest step: no downloads, no extra storage. The alternative — downloading the images once into the data directory, so covers also show offline and do not depend on Discogs keeping the addresses alive — is open
- **Albums that left Discogs but are kept**: an album that is not removed is listed again after every sync. Whether the user should be able to say "I still own this, stop asking" is left for later
- **Removed albums and older versions**: a removed album is left out when an older version is put back. A new album could in time get the id of a removed one and would then take its place in such a version; not handled
- **Vinyl detection edge case**: whether a "bonus disc" bundle (e.g. `"CD + LP"`) counts as vinyl is now a configurable setting (`count_bonus_discs_as_vinyl`, default `true` — see Configuration) rather than a fixed rule, so this no longer needs to be settled up front
- **Width-estimation constants**: the 0.5 cm base / +0.15 cm (180g) / +0.2 cm (gatefold) figures (see Sorting logic §3) are an untested starting assumption, now configurable in `config.yaml` — to be tuned against real shelf measurements. The same goes for the shelf widths estimated from the workbook's LP-units: the workbook counts a double album as 1.4 units, the app as two discs, so a shelf can look fuller than it is until its width is measured

### Parked from Phase 1a

Not blocking; set aside to be addressed later.

- **Screens not seen**: the upload and preview pages have only been exercised by tests. The light theme and the collapsed menu on a phone were looked at and approved (2026-10-08)
- **Topladers as a rotating sample**: decided (2026-10-08) that only shelves `a` and `b` of `Topladers` are rotating samples; shelf `c` is an ordinary shelf. The workbook lists the albums on `a` and `b` only there, without the real spot they are borrowed from, so they are still loaded as ordinary placements (see [Initial load](#initial-load)). Turning them into showcase features — and giving those albums their real spot — is open, and belongs with showcase management in Phase 2
- **`Overflow` and `Nieuwe koffer` locations**: the workbook lists these under `Kastindeling`, so they are loaded as ordinary Cabinets and show up as locations in Browse/Search. Neither is a real, existing storage spot (overflow is a proposal to give away, the cases are yet to be bought) — whether they should appear in the Unplaced albums list instead is undecided
