"""Optional OpenAI embeddings. Returns None when no key is configured (honest degradation)."""
from __future__ import annotations

import httpx

from .config import get_settings


async def embed(text: str) -> list[float] | None:
    s = get_settings()
    if not s.has_embeddings or not text.strip():
        return None
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {s.openai_api_key}"},
            json={"model": s.embed_model, "input": text[:8000]},
        )
        r.raise_for_status()
        return r.json()["data"][0]["embedding"]


def to_pgvector(vec: list[float]) -> str:
    """pgvector text literal, e.g. '[0.1,0.2,...]' — the reliable PostgREST cast path."""
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"
