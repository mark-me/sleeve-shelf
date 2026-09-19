# Requirements — Sleeve & Shelf

*As of: September 19, 2026*

**Sleeve & Shelf** is a self-hosted, open-source Python Flask web application (Bootstrap + JavaScript) that organizes a vinyl collection (~1089 titles, tracked on Discogs) across a record cabinet, based on musical kinship, artist era, and physical shelf space.

## Goal, scope, and phasing

### Phase 1 — MVP
- CSV import of a Discogs export, filtered to vinyl
- Manage storage structure: cabinets and shelves (width in cm, type top-loader/front-loader, layer top/bottom, reachability score, showcase flag for top-loaders)
- Manually create artist alias/project groups (e.g. related projects by the same person)
- Manually configure location rules: fixed exceptions (artist, alias group, or style → mandatory cabinet), separate from the automatic proposal
- Generate a sorting proposal following the sorting logic (see below)
- Proposal is fully adjustable by hand (move between shelves, reorder)
- Onboarding wizard for first-time setup
- No album covers — the standard Discogs CSV export does not include cover URLs

### Phase 2 — Ongoing management
- Discogs API integration alongside CSV (its own wizard step for setting up the personal access token)
- Add album covers to the Layout screen (Album gets a cover_url field)
- Add new purchases, with a suggested spot within the existing layout
- Suggestions for new location rules based on the existing layout — always requiring confirmation, never applied automatically
- Showcase management for the top-loaders (rotating samples from the collection)
- Notification + confirmation when a new purchase would shift an existing artist's dominant style (and thus its cluster)

### Phase 3 — Refinement
- Further refinement of musical kinship, independent of Discogs style tags
- Search and filter functionality
- Possibly later: other media formats (CD, etc.)

### Non-functional requirements
- Open source
- Single-user application
- Onboarding/guidance as an ongoing design principle for non-technical users — not just for the Discogs API integration, but also for setting up the storage structure and CSV import
- Self-hosted, deployed via Docker containers
- Strict separation of concerns: the sorting engine, persistence, and web layer are independent of each other

## Sorting logic

### 1. Clustering by musical kinship (style)
- Each artist gets one dominant Discogs style, based on the most albums in that style within the collection
- In case of a tie: the style of the earliest album (original release year) is decisive
- An artist always stays together as a whole — never split across clusters
- Style clusters are ordered relative to each other based on co-occurrence: styles that frequently appear together for artists with multiple albums in the collection are placed closer to one another
- Alias/project groups are treated as separate units within the cluster of their own dominant style

### 2. Era bands per artist
- Dynamic per artist: early/middle/late based on the spread of release years (original release year) within that artist's discography in the collection — not fixed decades
- An artist with a single album gets a single band (no early/middle/late split)
- Alias groups: each project gets its own era breakdown, not merged into a single timeline
- Alphabetical by album title within each era band

### 3. Physical placement
- Shelf width in cm determines how many records fit
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
- **Album**: id, artist_id, title, original release year, Discogs release ID, width (cm), list of styles, cover_url (empty until phase 2)
- **Style**: id, name (from Discogs)

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
1. **Ingestion**: CSV parser (phase 1), Discogs API client (phase 2) — both produce the same internal Album/Artist structure
2. **Domain**: the entities above, as plain domain objects, independent of storage
3. **Sorting engine**: pure logic in small, self-contained steps (determining dominant style, co-occurrence clustering, computing era bands, placement/width allocation) — operates on domain objects, with no knowledge of the database or web layer
4. **Persistence**: storage of all entities, independent of the sorting engine
5. **Web**: Flask routes/blueprints + Bootstrap/JS templates, including the onboarding wizard
6. **Confirmation layer**: a separate piece of logic that tracks proposals requiring confirmation (new style assignment, new location rule)

### Storage: files (JSON/CSV), no database
**Master data** (overwritable, no history needed):
- `artists.json`, `alias_groups.json`, `albums.json`, `cabinets.json`, `shelves.json`, `location_rules.json`, `style_assignments.json`

**Layout with history**:
- `placement_current.json` — active working state, overwritten on every change, no history
- `placements/` — directory of full snapshots, only created when the user explicitly chooses to "save this layout"; every snapshot is kept forever (no limit, no cleanup)

### Deployment
- Self-hosted, deployed via Docker containers
- File storage (JSON) mounted as a volume, so data persists outside the container

## Onboarding wizard

Strictly linear flow on first use; once completed, the regular application is freely navigable.

1. **Welcome/intro**
2. **Set up storage structure** — cabinets + shelves (type, layer, width, reachability, showcase flag)
3. **Import collection** — explanation of the Discogs CSV export, upload, automatic filtering to vinyl, preview of counts
4. **Alias/project groups** (optional, may be left empty)
5. **Location rules** (optional, may be left empty)
6. **First sorting proposal** — all style assignments are bulk-accepted, the full proposal (including placement) is shown immediately, individually correctable
7. **Save** — explicit action; the first version lands in `placements/`

## UI / screen layout

### Main navigation (after the wizard)
- **Dashboard** — overview: number of records, cabinets/shelves, last saved version
- **Layout** — core screen (see below)
- **Storage structure** — manage cabinets/shelves
- **Alias groups** — management screen
- **Location rules** — management screen
- **Showcase** — manage top-loaders/samples (phase 2)
- **Versions** — saved layouts, with the option to restore

No separate main-nav item for "Collection" — album/artist detail is reached by clicking an artist/era band in the Layout screen.

### Layout screen (core)
- One tab/dropdown per location (room); within a location, all cabinets in that room are stacked underneath one another
- Each cabinet shows its shelves, with a filled bar visualizing the occupied width
- Plain text in phase 1 (artist, era band, record count); album covers are only added in phase 2 (affects display only, not the data model)
- Drag-and-drop (e.g. via SortableJS) between or within shelves adjusts order/placement
- Clickable through to album/artist detail from an artist/era band

## Open questions
- None at this time — new questions will be added here as they come up
