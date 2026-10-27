"""Provider-neutral object-storage contracts and adapters."""

from backend.object_storage.interface import ObjectStorage
from backend.object_storage.schemas import StoredObjectMetadata, UploadInstructions

__all__ = ["ObjectStorage", "StoredObjectMetadata", "UploadInstructions"]
