"""Application composition for the configured object-storage adapter."""

from functools import lru_cache

from backend.config import Settings
from backend.object_storage.factory import ObjectStorageFactory
from backend.object_storage.gcs import GCSObjectStorage
from backend.object_storage.interface import ObjectStorage


@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStorage:
    settings = Settings()
    if not settings.storage_bucket.strip():
        raise ValueError("STORAGE_BUCKET must be configured")

    factory = ObjectStorageFactory(
        [
            GCSObjectStorage(
                bucket=settings.storage_bucket,
                project_id=settings.gcp_project_id,
            )
        ]
    )
    return factory.create(settings.storage_provider)
