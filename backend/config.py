from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    secret_key: str = "dev-only-change-me-parking-lot-secret-key-32chars"
    access_token_expire_minutes: int = 60
    algorithm: str = "HS256"
    database_url: str = "sqlite:///./parking.db"

    parking_level_count: int = 3
    tw_slots_per_level: int = 10
    fw_slots_per_level: int = 10

    tw_hourly_rate: str = "20.00"
    fw_hourly_rate: str = "40.00"
    tw_late_hourly_rate: str = "30.00"
    fw_late_hourly_rate: str = "60.00"

    admin_email: str = "admin@example.com"
    admin_password: str = "AdminPass123!"
    admin_name: str = "Parking Admin"


@lru_cache
def get_settings() -> Settings:
    return Settings()
