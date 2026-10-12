from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Custody Band Monitoring API"
    app_version: str = "0.1.0"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    firebase_project_id: str | None = None
    firebase_credentials_path: str | None = None
    firebase_credentials_json: str | None = None
    google_application_credentials: str | None = None
    firebase_emulator_host: str | None = None
    firebase_auth_emulator_host: str | None = None
    simulated_ingestion_enabled: bool = False
    device_online_timeout_seconds: int = 300
    offline_device_worker_enabled: bool = False
    offline_device_scan_interval_seconds: int = 60
    trip_idle_gap_seconds: int = Field(default=1800, ge=60, le=86_400)
    trip_min_distance_meters: float = Field(default=100.0, gt=0, le=100_000)
    low_battery_threshold: int = Field(default=20, ge=1, le=50)
    notification_mode: Literal["mock", "disabled"] = "mock"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
