import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    supabase_url: str = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    supabase_key: str = os.getenv("SUPABASE_KEY", "").strip()
    cors_origins_raw: str = os.getenv("CORS_ORIGINS", "http://localhost:5173").strip()

    # Shared secret required to call POST /api/refresh from the scheduled
    # GitHub Actions cron. If empty, the refresh endpoint refuses all calls.
    refresh_secret: str = os.getenv("REFRESH_SECRET", "").strip()

    # Resend (https://resend.com) — optional. If unset, email notifications
    # are skipped silently and only the in-app filings feed is updated.
    resend_api_key: str = os.getenv("RESEND_API_KEY", "").strip()
    resend_from: str = os.getenv("RESEND_FROM", "SedarWatchlist <onboarding@resend.dev>").strip()
    notify_email: str = os.getenv("NOTIFY_EMAIL", "").strip()

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @property
    def cors_allow_credentials(self) -> bool:
        return self.cors_origins != ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
