from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    app_name: str = "Wedding AI Photo Contest"
    app_url: str = "http://127.0.0.1:8000"
    admin_password: str | None = None

    data_backend: str = "sqlite"
    storage_backend: str = "local"
    firestore_project: str | None = None
    firestore_database: str = "(default)"
    gcs_bucket: str | None = None

    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'photo_contest.db').as_posix()}"
    data_dir: str = str(BASE_DIR / "data")
    upload_dir: str = str(BASE_DIR / "data" / "uploads")

    default_event_title: str = "AI Photo Contest"
    default_event_subtitle: str = "April 19, 2026 at The Prince Park Tower Tokyo"
    default_venue: str = "The Prince Park Tower Tokyo / Sky Banquet"
    default_event_date: str = "2026-04-19"

    ai_provider: str = "auto"
    google_api_key: str | None = None
    google_model: str = "gemini-2.5-flash"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "gemma3:4b"
    cloud_tasks_project: str | None = None
    cloud_tasks_location: str | None = None
    cloud_tasks_queue: str | None = None
    cloud_tasks_token: str | None = None

    max_upload_mb: int = 20
    target_image_max_edge: int = 1600
    target_image_quality: int = 80

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    @property
    def upload_path(self) -> Path:
        return Path(self.upload_dir)


@lru_cache
def get_settings() -> Settings:
    return Settings()
