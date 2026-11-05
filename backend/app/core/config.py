from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]  # the crisisgrid folder


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://crisis:crisis@localhost:5433/crisisgrid"
    redis_url: str = "redis://localhost:6380/0"
    osrm_url: str = "http://localhost:5001"
    zone_name: str = "amritsar_core"
    fallback_speed_kmh: float = 30.0

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")


settings = Settings()