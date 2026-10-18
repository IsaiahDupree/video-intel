"""Obsidian cockpit: generate one Dataview-queryable markdown note per video FROM Supabase.

The vault is a read-view of the canonical DB, never the source of truth. Notes carry YAML
frontmatter so Dataview can query the library ("all UGC-format videos with roas > 2", etc.).
"""
from __future__ import annotations

import os
from typing import Any

from .config import get_settings


def _yaml_scalar(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace('"', '\\"')
    return f'"{s}"'


def render_note(video: dict, observations: list[dict], outcomes: list[dict]) -> str:
    hooks = [o for o in observations if o.get("kind") == "hook"]
    formats = [o for o in observations if o.get("kind") == "format"]
    transcripts = [o for o in observations if o.get("kind") == "transcript"]
    scenes = [o for o in observations if o.get("kind") == "scene"]

    fm: dict[str, Any] = {
        "mvi_id": video["id"],
        "slug": video["slug"],
        "title": video.get("title") or video["slug"],
        "source_system": video.get("source_system"),
        "status": video.get("status"),
        "duration_seconds": video.get("duration_seconds"),
        "storage_path": video.get("storage_path"),
        "content_hash": video.get("content_hash"),
        "n_observations": len(observations),
        "n_outcomes": len(outcomes),
    }
    # promote key content-intelligence fields to frontmatter for Dataview filtering
    if formats:
        fmt_payload = formats[0].get("payload") or {}
        for k in ("ugc_format", "content_tier", "energy_level", "is_talking_head"):
            if k in fmt_payload:
                fm[k] = fmt_payload[k]

    lines = ["---"]
    for k, v in fm.items():
        lines.append(f"{k}: {_yaml_scalar(v)}")
    lines.append("tags: [marketing-video, mvi]")
    lines.append("---")
    lines.append("")
    lines.append(f"# {fm['title']}")
    lines.append("")
    lines.append(f"> Canonical record `{video['id']}` — generated from Supabase (`mvi_video`). "
                 f"Edit the database, not this note.")
    lines.append("")

    if hooks:
        lines.append("## Hooks")
        for h in hooks:
            t = f"[{h.get('t_start')}s]" if h.get("t_start") is not None else ""
            lines.append(f"- {t} {h.get('text_span') or ''}".rstrip())
        lines.append("")

    if formats:
        lines.append("## Format / classification")
        for f in formats:
            payload = f.get("payload") or {}
            for k, v in payload.items():
                lines.append(f"- **{k}**: {v}")
        lines.append("")

    if scenes:
        lines.append("## Scenes")
        for s in scenes:
            span = f"[{s.get('t_start')}–{s.get('t_end')}s]" if s.get("t_start") is not None else ""
            lines.append(f"- {span} {s.get('text_span') or ''}".rstrip())
        lines.append("")

    if transcripts:
        lines.append("## Transcript")
        for t in transcripts:
            lines.append(t.get("text_span") or "")
        lines.append("")

    if outcomes:
        lines.append("## Outcomes")
        lines.append("")
        lines.append("| platform | metric | value | observed |")
        lines.append("|---|---|---:|---|")
        for o in outcomes:
            lines.append(f"| {o.get('platform') or ''} | {o.get('metric')} | "
                         f"{o.get('value')} | {o.get('observed_at','')[:10]} |")
        lines.append("")

    return "\n".join(lines)


def write_note(video: dict, observations: list[dict], outcomes: list[dict]) -> str | None:
    """Write the note into the vault. Returns the path, or None if no vault is configured."""
    s = get_settings()
    if not s.has_vault:
        return None
    folder = os.path.join(s.obsidian_vault, s.obsidian_subdir)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{video['slug']}.md")
    with open(path, "w") as f:
        f.write(render_note(video, observations, outcomes))
    return path
