#!/usr/bin/env python3
"""Backfill the index from the MediaPoster project (ivhfuhxorppptyuofbgq).

Reads existing analysis (analyzed_videos + video_segments) and mirrors it into the hub as
mvi_video + mvi_observation. This is how the 'build something new' index reuses the deep
extraction MediaPoster already produced instead of re-analyzing 2,423 videos from scratch.

Requires MEDIA_SUPABASE_URL / MEDIA_SUPABASE_SERVICE_KEY in .env. Run:  python import_mediaposter.py
"""
from __future__ import annotations

import asyncio
import hashlib

from app.db import hub, media_source
from app.media import slugify


def _synthetic_hash(source_ref: str) -> str:
    # When the underlying file isn't mounted, derive a stable dedup key from the source id.
    return "mp:" + hashlib.sha256(source_ref.encode()).hexdigest()


async def main(limit: int = 500) -> None:
    src = media_source()
    if src is None:
        raise SystemExit("MEDIA_SUPABASE_URL / MEDIA_SUPABASE_SERVICE_KEY not configured in .env")
    dst = hub()

    videos = await src.select("analyzed_videos", params={"select": "*", "limit": str(limit)})
    print(f"pulled {len(videos)} analyzed_videos from MediaPoster")

    imported = 0
    for v in videos:
        vid_ref = str(v.get("id") or v.get("video_id") or "")
        if not vid_ref:
            continue
        row = {
            "content_hash": _synthetic_hash(vid_ref),
            "slug": slugify(v.get("title") or v.get("filename") or f"mp-{vid_ref}"),
            "title": v.get("title") or v.get("filename"),
            "source_system": "mediaposter",
            "source_project": "ivhfuhxorppptyuofbgq",
            "source_table": "analyzed_videos",
            "source_ref": vid_ref,
            "storage_path": v.get("file_path") or v.get("local_path"),
            "duration_seconds": v.get("duration"),
            "status": "indexed",
            "metadata": {"imported_from": "mediaposter"},
        }
        res = await dst.insert("mvi_video", row, upsert_on="content_hash")
        mvi_id = res[0]["id"] if res else None
        if not mvi_id:
            continue

        # transcript observation (whole-video span)
        transcript = v.get("transcript") or v.get("transcription")
        if transcript:
            await dst.insert("mvi_observation", {
                "video_id": mvi_id, "kind": "transcript",
                "text_span": str(transcript)[:20000],
                "extracted_by": "mediaposter:analyzed_videos", "source_ref": vid_ref,
            })

        # per-segment observations (hook/context/body/cta with psychology tags)
        segs = await src.select("video_segments",
                                params={"select": "*", "video_id": f"eq.{vid_ref}"})
        for seg in segs:
            await dst.insert("mvi_observation", {
                "video_id": mvi_id,
                "kind": "hook" if (seg.get("segment_type") == "hook") else "scene",
                "t_start": seg.get("start_time"), "t_end": seg.get("end_time"),
                "text_span": seg.get("text") or seg.get("content"),
                "payload": {k: seg.get(k) for k in ("segment_type", "fate_tag", "aida_tag")
                            if seg.get(k) is not None},
                "extracted_by": "mediaposter:video_segments", "source_ref": vid_ref,
            })
        imported += 1

    print(f"imported {imported} videos into the hub (mvi_video + mvi_observation)")


if __name__ == "__main__":
    asyncio.run(main())
