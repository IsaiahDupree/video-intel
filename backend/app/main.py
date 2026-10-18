"""video-intel :: source-grounded Marketing Video Intelligence service.

Layers (kept separate, per the architecture): mvi_video (immutable registry) ->
mvi_observation (facts @ timecode + embedding) -> mvi_outcome (perf ledger) ->
mvi_claim (vetted beliefs). Obsidian is a generated read-view. intel-node is the query surface.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import media as media_mod
from . import obsidian
from .config import get_settings
from .db import hub
from .embeddings import embed, to_pgvector

app = FastAPI(title="video-intel", version="0.1.0",
              description="Source-grounded Marketing Video Intelligence index")


# --------------------------------------------------------------------------- models
class IndexRequest(BaseModel):
    path: str = Field(..., description="Absolute path to the video file (e.g. on /Volumes/My Passport)")
    title: Optional[str] = None
    source_system: str = "manual"
    source_project: Optional[str] = None
    source_table: Optional[str] = None
    source_ref: Optional[str] = None
    storage_url: Optional[str] = None
    metadata: dict[str, Any] = {}


class ObservationIn(BaseModel):
    video_id: str
    kind: str = Field(..., description="hook | format | transcript | scene | caption | claim_extract | tag")
    text_span: Optional[str] = None
    t_start: Optional[float] = None
    t_end: Optional[float] = None
    payload: dict[str, Any] = {}
    extracted_by: Optional[str] = None
    source_ref: Optional[str] = None
    confidence: Optional[float] = None


class OutcomeIn(BaseModel):
    video_id: str
    metric: str
    value: float
    platform: Optional[str] = None
    campaign_ref: Optional[str] = None
    post_ref: Optional[str] = None
    unit: Optional[str] = None
    observed_at: Optional[str] = None
    source_system: Optional[str] = None


class ClaimIn(BaseModel):
    statement: str
    domain: Optional[str] = None
    confidence: Optional[float] = None
    verification_status: str = "proposed"
    supporting_observation_ids: list[str] = []
    contradicting_observation_ids: list[str] = []
    supporting_outcome_ids: list[str] = []
    supersedes_claim_id: Optional[str] = None
    created_by: Optional[str] = None


# --------------------------------------------------------------------------- health
@app.get("/api/health")
async def health():
    s = get_settings()
    status = {
        "service": "video-intel",
        "ok": True,
        "capabilities": {
            "supabase_hub": s.has_supabase,
            "embeddings": s.has_embeddings,
            "obsidian_vault": s.has_vault,
            "media_source_import": s.has_media_source,
            "ffprobe": bool(media_mod.shutil.which("ffprobe")),
        },
    }
    if s.has_supabase:
        try:
            rows = await hub().select("mvi_video", params={"select": "id", "limit": "1"})
            status["hub_reachable"] = True
            status["hub_note"] = f"mvi_video reachable ({'has rows' if rows else 'empty'})"
        except Exception as e:  # noqa: BLE001 — surface the real reason honestly
            status["ok"] = False
            status["hub_reachable"] = False
            status["error"] = str(e)
    else:
        status["ok"] = False
        status["error"] = "SUPABASE not configured"
    return status


# --------------------------------------------------------------------------- index
@app.post("/api/index")
async def index_video(req: IndexRequest):
    """Register a video: content-hash + real ffprobe metadata -> upsert mvi_video (dedup by hash)."""
    if not os.path.isfile(req.path):
        raise HTTPException(404, f"file not found: {req.path}")

    db = hub()
    content_hash = media_mod.sha256_file(req.path)
    meta = media_mod.ffprobe(req.path)
    slug = media_mod.slugify(req.title or req.path)

    row = {
        "content_hash": content_hash,
        "slug": slug,
        "title": req.title or os.path.basename(req.path),
        "source_system": req.source_system,
        "source_project": req.source_project,
        "source_table": req.source_table,
        "source_ref": req.source_ref,
        "storage_path": req.path,
        "storage_url": req.storage_url,
        "file_size_bytes": os.path.getsize(req.path),
        "status": "registered",
        "metadata": req.metadata,
        **meta,
    }
    try:
        result = await db.insert("mvi_video", row, upsert_on="content_hash")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"insert failed: {e}") from e
    video = result[0] if result else row
    await db.insert("mvi_agent_run", {
        "kind": "index", "status": "completed",
        "video_id": video.get("id"), "detail": {"path": req.path, "hash": content_hash},
    })
    return {"video": video, "deduped": bool(result and result[0].get("content_hash") == content_hash)}


# --------------------------------------------------------------------------- observe
@app.post("/api/observe")
async def add_observation(obs: ObservationIn):
    """Attach an extracted fact to a video. Embeds text_span if an embedder is configured."""
    db = hub()
    row = obs.model_dump()
    vec = await embed(obs.text_span or "") if obs.text_span else None
    if vec:
        row["embedding"] = to_pgvector(vec)
    result = await db.insert("mvi_observation", row)
    return {"observation": result[0] if result else row, "embedded": bool(vec)}


# --------------------------------------------------------------------------- outcome
@app.post("/api/outcome")
async def add_outcome(o: OutcomeIn):
    db = hub()
    row = {k: v for k, v in o.model_dump().items() if v is not None}
    result = await db.insert("mvi_outcome", row)
    return {"outcome": result[0] if result else row}


# --------------------------------------------------------------------------- claim
@app.post("/api/claim")
async def add_claim(c: ClaimIn):
    db = hub()
    result = await db.insert("mvi_claim", c.model_dump())
    return {"claim": result[0] if result else c.model_dump()}


# --------------------------------------------------------------------------- search
@app.get("/api/search")
async def search(q: str, limit: int = 10, kind: Optional[str] = None):
    """Semantic (pgvector) when embeddings are on, else fuzzy-text (pg_trgm). Honest either way."""
    db = hub()
    mode = "text"
    vec = await embed(q)
    if vec:
        mode = "semantic"
        hits = await db.rpc("mvi_match_observations", {
            "query_embedding": to_pgvector(vec), "match_count": limit, "filter_kind": kind,
        })
    else:
        hits = await db.rpc("mvi_search_text", {"q": q, "match_count": limit})

    # hydrate videos for the matched observations
    video_ids = list({h["video_id"] for h in hits})
    videos: dict[str, dict] = {}
    if video_ids:
        in_list = ",".join(video_ids)
        rows = await db.select("mvi_video", params={"id": f"in.({in_list})", "select": "*"})
        videos = {v["id"]: v for v in rows}
    return {"mode": mode, "query": q, "matches": [
        {"observation": h, "video": videos.get(h["video_id"])} for h in hits
    ]}


# --------------------------------------------------------------------------- obsidian sync
@app.post("/api/sync-obsidian")
async def sync_obsidian(video_id: Optional[str] = None, limit: int = 200):
    """Regenerate vault notes FROM Supabase (truth -> cockpit). One note per video."""
    s = get_settings()
    if not s.has_vault:
        raise HTTPException(400, f"OBSIDIAN_VAULT not set or not a directory: {s.obsidian_vault!r}")
    db = hub()
    if video_id:
        vids = await db.select("mvi_video", params={"id": f"eq.{video_id}", "select": "*"})
    else:
        vids = await db.select("mvi_video", params={"select": "*", "limit": str(limit),
                                                    "order": "created_at.desc"})
    written = []
    for v in vids:
        obs = await db.select("mvi_observation",
                              params={"video_id": f"eq.{v['id']}", "select": "*",
                                      "order": "t_start.asc.nullsfirst"})
        outs = await db.select("mvi_outcome",
                               params={"video_id": f"eq.{v['id']}", "select": "*",
                                       "order": "observed_at.desc"})
        path = obsidian.write_note(v, obs, outs)
        if path:
            written.append(path)
    return {"written": len(written), "notes": written[:20], "vault": s.obsidian_vault}
