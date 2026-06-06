import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_key: str = os.getenv("SUPABASE_KEY", "")
    cors_origins: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
        if origin.strip()
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
