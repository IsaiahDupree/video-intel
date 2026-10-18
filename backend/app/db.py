"""Thin async PostgREST client for the Supabase hub. Real HTTP, service-role auth, no ORM."""
from __future__ import annotations

from typing import Any

import httpx

from .config import get_settings


class Supabase:
    """Minimal PostgREST + RPC wrapper over the hub. Uses the service key (bypasses RLS)."""

    def __init__(self, url: str, key: str) -> None:
        self._base = f"{url}/rest/v1"
        self._headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    async def insert(self, table: str, rows: list[dict] | dict, *, upsert_on: str | None = None) -> list[dict]:
        headers = dict(self._headers)
        prefer = ["return=representation"]
        if upsert_on:
            prefer.append("resolution=merge-duplicates")
        headers["Prefer"] = ",".join(prefer)
        params = {"on_conflict": upsert_on} if upsert_on else None
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self._base}/{table}", headers=headers, json=rows, params=params)
            r.raise_for_status()
            return r.json()

    async def select(self, table: str, *, params: dict[str, Any] | None = None) -> list[dict]:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{self._base}/{table}", headers=self._headers, params=params or {})
            r.raise_for_status()
            return r.json()

    async def update(self, table: str, match: dict[str, str], patch: dict) -> list[dict]:
        headers = dict(self._headers)
        headers["Prefer"] = "return=representation"
        params = {k: f"eq.{v}" for k, v in match.items()}
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.patch(f"{self._base}/{table}", headers=headers, params=params, json=patch)
            r.raise_for_status()
            return r.json()

    async def rpc(self, fn: str, args: dict) -> Any:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self._base}/rpc/{fn}", headers=self._headers, json=args)
            r.raise_for_status()
            return r.json()


def hub() -> Supabase:
    s = get_settings()
    if not s.has_supabase:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY not configured")
    return Supabase(s.supabase_url, s.supabase_service_key)


def media_source() -> Supabase | None:
    """The MediaPoster project (ivhfuhxorppptyuofbgq) — source of existing analysis. Optional."""
    s = get_settings()
    if not s.has_media_source:
        return None
    return Supabase(s.media_supabase_url, s.media_supabase_service_key)
