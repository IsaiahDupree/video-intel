# video-intel

Source-grounded **Marketing Video Intelligence** — turns a pile of marketing videos into a
vetted, queryable institutional index. Obsidian is the analyst cockpit; Supabase is the
canonical truth; intel-node is the query surface. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

Built as the "central intelligence" layer from the source-grounded architecture, cut down to
infra this machine already runs — no Temporal / OpenMetadata / Onyx / Graphiti to babysit.

## Status

- ✅ Schema live on hub `gqjgxltroyysjoxswbmn` — `mvi_video`, `mvi_observation`,
  `mvi_outcome`, `mvi_claim`, `mvi_agent_run` (all RLS-enabled). Migrations in `schema/`.
- ✅ Retrieval RPCs live — `mvi_match_observations` (pgvector cosine), `mvi_search_text`
  (word_similarity + ILIKE). Verified end-to-end with real rows.
- ✅ FastAPI service (`backend/`) — 7 routes, loads clean. Obsidian renderer verified.
- ⏳ **One missing config**: drop a `service_role` key into `backend/.env` to run the HTTP server
  (intel-node only stores the anon key). Everything else is wired.

## Object model (the five separations)

| Table | Holds | Rule |
|---|---|---|
| `mvi_video` | immutable registry, one row per unique video (SHA-256) | never mutated |
| `mvi_observation` | facts @ timecode + pgvector embedding | every fact has provenance span |
| `mvi_outcome` | performance ledger (video × platform × metric over time) | temporal |
| `mvi_claim` | vetted beliefs w/ `valid_from`/`valid_to`/`supersedes` | evidence-linked |
| `mvi_agent_run` | provenance of every index/analyze/sync op | audit trail |

## Run

```bash
cd backend
cp .env.example .env         # then set SUPABASE_SERVICE_KEY (service_role, from hub project settings)
./run.sh                      # venv + deps + uvicorn on :5570
curl localhost:5570/api/health
```

`/api/health` reports capability flags — it degrades honestly: no OpenAI key → fuzzy-text search
instead of semantic; no vault dir → Obsidian sync disabled; no ffprobe → metadata stays null.

## API

| Route | Purpose |
|---|---|
| `POST /api/index` | register a video file → SHA-256 + ffprobe metadata → upsert `mvi_video` (dedup) |
| `POST /api/observe` | attach an extracted fact (hook/format/transcript/scene) + auto-embed |
| `POST /api/outcome` | attach a performance datapoint |
| `POST /api/claim` | assert/supersede a vetted claim with supporting observation IDs |
| `GET  /api/search?q=` | semantic (pgvector) or fuzzy-text retrieval → videos + matching spans |
| `POST /api/sync-obsidian` | regenerate vault notes from Supabase (truth → cockpit) |
| `GET  /api/health` | Supabase + vault reachability + capability flags |

## Backfill from existing analysis

MediaPoster (project `ivhfuhxorppptyuofbgq`) already holds deep per-segment/word/frame analysis
for the corpus. Instead of re-analyzing 2,423 videos, mirror it:

```bash
cd backend && python import_mediaposter.py   # needs MEDIA_SUPABASE_* in .env
```

## Corpus

Videos live on `/Volumes/My Passport/` (drive must be mounted). Media Vault tracks the file
inventory (`mv_media_items`, SHA-256 + dedup); MediaPoster holds the analysis; Foundry generates
new ones. video-intel federates all three under one permanent-ID space via soft `source_ref`
pointers (cross-project, so no hard FKs).

## Obsidian setup (one-time)

Vault: `~/Library/Mobile Documents/com~apple~CloudDocs/ObsidianVaults/research-vault`. Notes land
under `Marketing-Videos/`. Install **Dataview** to query the library, e.g.:

````
```dataview
TABLE ugc_format, content_tier, n_outcomes
FROM #mvi
SORT n_outcomes DESC
```
````
