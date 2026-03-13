from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from google.cloud import storage
from google.cloud.exceptions import NotFound

from app.config import Settings
from app.config import get_settings


class BaseImageStorage:
    def ensure_ready(self) -> None:
        return None

    def save_image(self, *, key: str, data: bytes, content_type: str) -> str:
        raise NotImplementedError

    def read_image(self, key: str) -> bytes:
        raise NotImplementedError

    def delete_image(self, key: str) -> None:
        raise NotImplementedError


class LocalImageStorage(BaseImageStorage):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def ensure_ready(self) -> None:
        self.settings.data_path.mkdir(parents=True, exist_ok=True)
        self.settings.upload_path.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        return self.settings.upload_path / key

    def save_image(self, *, key: str, data: bytes, content_type: str) -> str:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def read_image(self, key: str) -> bytes:
        return self._path_for(key).read_bytes()

    def delete_image(self, key: str) -> None:
        path = self._path_for(key)
        if path.exists():
            path.unlink()


class GCSImageStorage(BaseImageStorage):
    def __init__(self, settings: Settings) -> None:
        if not settings.gcs_bucket:
            raise RuntimeError("GCS_BUCKET is required when STORAGE_BACKEND=gcs.")
        self.bucket_name = settings.gcs_bucket
        self.client = storage.Client(project=settings.firestore_project or None)
        self.bucket = self.client.bucket(self.bucket_name)

    def save_image(self, *, key: str, data: bytes, content_type: str) -> str:
        blob = self.bucket.blob(key)
        blob.upload_from_string(data, content_type=content_type, timeout=60)
        return key

    def read_image(self, key: str) -> bytes:
        blob = self.bucket.blob(key)
        return blob.download_as_bytes(timeout=60)

    def delete_image(self, key: str) -> None:
        blob = self.bucket.blob(key)
        try:
            blob.delete(timeout=60)
        except NotFound:
            return None


@lru_cache
def get_storage() -> BaseImageStorage:
    settings = get_settings()
    if settings.storage_backend.lower() == "gcs":
        return GCSImageStorage(settings)
    return LocalImageStorage(settings)
