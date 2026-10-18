-- video-intel :: retrieval RPCs (called by the FastAPI service via PostgREST /rpc)
-- Semantic (pgvector cosine) + fuzzy-text (pg_trgm). Embedding passed as text -> cast to vector,
-- which is the reliable PostgREST path (jsonb arrays don't auto-coerce to vector).

create or replace function public.mvi_match_observations(
  query_embedding text,
  match_count     int  default 10,
  filter_kind     text default null
)
returns table (
  id         uuid,
  video_id   uuid,
  kind       text,
  text_span  text,
  t_start    numeric,
  t_end      numeric,
  payload    jsonb,
  similarity double precision
)
language sql stable
set search_path = public, extensions
as $$
  select o.id, o.video_id, o.kind, o.text_span, o.t_start, o.t_end, o.payload,
         1 - (o.embedding <=> query_embedding::vector) as similarity
  from public.mvi_observation o
  where o.embedding is not null
    and (filter_kind is null or o.kind = filter_kind)
  order by o.embedding <=> query_embedding::vector
  limit match_count;
$$;

create or replace function public.mvi_search_text(
  q           text,
  match_count int default 20
)
returns table (
  id        uuid,
  video_id  uuid,
  kind      text,
  text_span text,
  t_start   numeric,
  t_end     numeric,
  sim       real
)
language sql stable
set search_path = public, extensions
as $$
  -- word_similarity ranks how well the query matches a CONTIGUOUS extent of a longer span
  -- (right for "phrase inside transcript"); ILIKE catches exact-substring hits trigrams miss.
  select o.id, o.video_id, o.kind, o.text_span, o.t_start, o.t_end,
         word_similarity(q, o.text_span) as sim
  from public.mvi_observation o
  where o.text_span is not null
    and (word_similarity(q, o.text_span) > 0.2 or o.text_span ilike '%' || q || '%')
  order by word_similarity(q, o.text_span) desc
  limit match_count;
$$;
