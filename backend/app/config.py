import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    supabase_url: str = os.getenv("SUPABASE_URL", "").strip()
    supabase_key: str = os.getenv("SUPABASE_KEY", "").strip()
    cors_origins_raw: str = os.getenv("CORS_ORIGINS", "http://localhost:5173").strip()

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @property
    def cors_allow_credentials(self) -> bool:
        # The CORS spec forbids credentials with a wildcard origin.
        return self.cors_origins != ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
