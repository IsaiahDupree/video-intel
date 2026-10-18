"""Runtime configuration for the video-intel service (env-driven, no hardcoded secrets)."""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    def __init__(self) -> None:
        self.supabase_url: str = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.supabase_service_key: str = os.getenv("SUPABASE_SERVICE_KEY", "")

        self.obsidian_vault: str = os.getenv("OBSIDIAN_VAULT", "")
        self.obsidian_subdir: str = os.getenv("OBSIDIAN_SUBDIR", "Marketing-Videos")

        self.openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
        self.embed_model: str = os.getenv("EMBED_MODEL", "text-embedding-3-small")

        self.media_supabase_url: str = os.getenv("MEDIA_SUPABASE_URL", "").rstrip("/")
        self.media_supabase_service_key: str = os.getenv("MEDIA_SUPABASE_SERVICE_KEY", "")

        self.port: int = int(os.getenv("PORT", "5570"))

    # --- capability flags: the service degrades honestly when a capability is absent ---
    @property
    def has_supabase(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)

    @property
    def has_embeddings(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_vault(self) -> bool:
        return bool(self.obsidian_vault) and os.path.isdir(self.obsidian_vault)

    @property
    def has_media_source(self) -> bool:
        return bool(self.media_supabase_url and self.media_supabase_service_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
