"""Real media inspection: SHA-256 content hashing + ffprobe metadata. No mock values."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from typing import Any


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def slugify(name: str) -> str:
    base = os.path.splitext(os.path.basename(name))[0].lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base or "video"


def ffprobe(path: str) -> dict[str, Any]:
    """Return real container/stream metadata via ffprobe. Empty dict if ffprobe is unavailable."""
    if not shutil.which("ffprobe"):
        return {}
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode != 0:
            return {}
        data = json.loads(out.stdout or "{}")
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return {}

    fmt = data.get("format", {})
    vstream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    meta: dict[str, Any] = {}
    if fmt.get("duration"):
        try:
            meta["duration_seconds"] = round(float(fmt["duration"]), 3)
        except ValueError:
            pass
    if vstream.get("width"):
        meta["width"] = int(vstream["width"])
    if vstream.get("height"):
        meta["height"] = int(vstream["height"])
    if fmt.get("format_name"):
        meta["format"] = fmt["format_name"]
    return meta
