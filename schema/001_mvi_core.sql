-- video-intel :: source-grounded Marketing Video Intelligence
-- Migration 001 — canonical object model, prefix mvi_ (collision-safe in shared hub gqjgxltroyysjoxswbmn)
-- Implements the five separations: media / observation / outcome / claim / agent-run.
-- pgvector 0.8.0 confirmed present (hnsw). All FKs are intra-project; cross-project links to
-- media data (project ivhfuhxorppptyuofbgq) are SOFT pointers (source_system/source_table/source_ref).

-- pg_trgm powers fuzzy text search over observation spans; install into the extensions schema.
create extension if not exists pg_trgm with schema extensions;

-- ---------------------------------------------------------------------------
-- 1. mvi_video — canonical immutable registry, one row per unique video (by content hash)
-- ---------------------------------------------------------------------------
create table if not exists public.mvi_video (
  id                uuid primary key default gen_random_uuid(),
  content_hash      text not null unique,                 -- SHA-256 dedup key
  slug              text not null unique,                 -- human id -> Obsidian filename
  title             text,
  source_system     text not null default 'manual',       -- media_vault | mediaposter | foundry | manual
  source_project    text,                                 -- supabase project ref the source row lives in
  source_table      text,                                 -- e.g. mv_media_items, analyzed_videos
  source_ref        text,                                 -- id in the source system (soft pointer, no FK)
  storage_path      text,                                 -- canonical file path (usually /Volumes/My Passport/...)
  storage_url       text,                                 -- public/CDN url if published
  duration_seconds  numeric,
  width             int,
  height            int,
  format            text,
  file_size_bytes   bigint,
  status            text not null default 'registered',   -- registered | analyzing | indexed | error
  analyzed_at       timestamptz,
  metadata          jsonb not null default '{}'::jsonb,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create index if not exists mvi_video_status_idx        on public.mvi_video (status);
create index if not exists mvi_video_source_system_idx  on public.mvi_video (source_system);
create index if not exists mvi_video_metadata_gin       on public.mvi_video using gin (metadata);

-- ---------------------------------------------------------------------------
-- 2. mvi_observation — extracted facts w/ provenance span + semantic embedding
-- ---------------------------------------------------------------------------
create table if not exists public.mvi_observation (
  id            uuid primary key default gen_random_uuid(),
  video_id      uuid not null references public.mvi_video(id) on delete cascade,
  kind          text not null,                            -- hook | format | transcript | scene | caption | claim_extract | tag
  t_start       numeric,                                  -- provenance: start second in the video
  t_end         numeric,                                  -- provenance: end second
  text_span     text,                                     -- the observed text / description
  payload       jsonb not null default '{}'::jsonb,       -- structured facts (ugc_format, shot_type, objects, sentiment...)
  embedding     vector(1536),                             -- text-embedding-3-small dim; nullable until embedded
  extracted_by  text,                                     -- model/agent/run that produced it
  source_ref    text,                                     -- link to underlying mediaposter/mv row if mirrored
  confidence    numeric,
  created_at    timestamptz not null default now()
);
create index if not exists mvi_observation_video_idx on public.mvi_observation (video_id);
create index if not exists mvi_observation_kind_idx  on public.mvi_observation (kind);
create index if not exists mvi_observation_payload_gin on public.mvi_observation using gin (payload);
create index if not exists mvi_observation_text_trgm on public.mvi_observation using gin (text_span extensions.gin_trgm_ops);
-- hnsw semantic index (cosine). Built now; fine on empty table, grows incrementally.
create index if not exists mvi_observation_embed_hnsw on public.mvi_observation
  using hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- 3. mvi_outcome — performance ledger, temporal (video x platform x metric over time)
-- ---------------------------------------------------------------------------
create table if not exists public.mvi_outcome (
  id            uuid primary key default gen_random_uuid(),
  video_id      uuid not null references public.mvi_video(id) on delete cascade,
  platform      text,                                     -- instagram | tiktok | youtube | twitter | facebook | meta_ads
  campaign_ref  text,
  post_ref      text,
  metric        text not null,                            -- views | likes | spend | conversions | ctr | retention_3s | roas
  value         numeric not null,
  unit          text,
  observed_at   timestamptz not null default now(),       -- temporal key
  source_system text,
  created_at    timestamptz not null default now()
);
create index if not exists mvi_outcome_video_idx   on public.mvi_outcome (video_id);
create index if not exists mvi_outcome_platform_idx on public.mvi_outcome (platform);
create index if not exists mvi_outcome_metric_idx  on public.mvi_outcome (metric);
create index if not exists mvi_outcome_observed_idx on public.mvi_outcome (observed_at desc);

-- ---------------------------------------------------------------------------
-- 4. mvi_claim — vetted beliefs w/ temporal validity + supersession
-- ---------------------------------------------------------------------------
create table if not exists public.mvi_claim (
  id                          uuid primary key default gen_random_uuid(),
  statement                   text not null,
  domain                      text,                       -- hook | format | timing | platform | audience
  confidence                  numeric,
  verification_status         text not null default 'proposed', -- proposed | supported | contradicted | retired
  supporting_observation_ids  uuid[] not null default '{}',
  contradicting_observation_ids uuid[] not null default '{}',
  supporting_outcome_ids      uuid[] not null default '{}',
  valid_from                  timestamptz not null default now(),
  valid_to                    timestamptz,                -- null = currently valid
  supersedes_claim_id         uuid references public.mvi_claim(id),
  created_by                  text,
  created_at                  timestamptz not null default now()
);
create index if not exists mvi_claim_status_idx on public.mvi_claim (verification_status);
create index if not exists mvi_claim_domain_idx on public.mvi_claim (domain);
create index if not exists mvi_claim_valid_idx  on public.mvi_claim (valid_to);

-- ---------------------------------------------------------------------------
-- 5. mvi_agent_run — provenance ledger for extraction/index/sync operations
-- ---------------------------------------------------------------------------
create table if not exists public.mvi_agent_run (
  id          uuid primary key default gen_random_uuid(),
  kind        text not null,                              -- index | analyze | embed | claim | sync_obsidian | outcome_pull
  status      text not null default 'started',            -- started | completed | error
  video_id    uuid references public.mvi_video(id) on delete set null,
  detail      jsonb not null default '{}'::jsonb,
  started_at  timestamptz not null default now(),
  finished_at timestamptz
);
create index if not exists mvi_agent_run_kind_idx on public.mvi_agent_run (kind);
create index if not exists mvi_agent_run_video_idx on public.mvi_agent_run (video_id);

-- ---------------------------------------------------------------------------
-- updated_at trigger for mvi_video (moddatetime available)
-- ---------------------------------------------------------------------------
create or replace function public.mvi_touch_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;

drop trigger if exists mvi_video_touch on public.mvi_video;
create trigger mvi_video_touch before update on public.mvi_video
  for each row execute function public.mvi_touch_updated_at();

-- ---------------------------------------------------------------------------
-- RLS: enable on all mvi_ tables. service_role (backend) bypasses RLS.
-- authenticated gets read for the future intel-node/portal query surface.
-- ---------------------------------------------------------------------------
alter table public.mvi_video       enable row level security;
alter table public.mvi_observation enable row level security;
alter table public.mvi_outcome     enable row level security;
alter table public.mvi_claim       enable row level security;
alter table public.mvi_agent_run   enable row level security;

do $$
declare t text;
begin
  foreach t in array array['mvi_video','mvi_observation','mvi_outcome','mvi_claim','mvi_agent_run'] loop
    execute format('drop policy if exists %I on public.%I', t||'_auth_read', t);
    execute format('create policy %I on public.%I for select to authenticated using (true)', t||'_auth_read', t);
  end loop;
end $$;
