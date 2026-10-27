"""Registry used to select a configured storage adapter by provider name."""

from collections.abc import Iterable

from backend.object_storage.interface import ObjectStorage


class ObjectStorageFactory:
    def __init__(self, backends: Iterable[ObjectStorage] = ()):
        self._backends: dict[str, ObjectStorage] = {}
        for backend in backends:
            self.register(backend)

    def register(self, backend: ObjectStorage) -> None:
        provider = backend.provider.strip()
        if not provider:
            raise ValueError("storage provider must be nonempty")
        if provider in self._backends:
            raise ValueError(f"storage provider already registered: {provider}")
        self._backends[provider] = backend

    def create(self, provider: str) -> ObjectStorage:
        try:
            return self._backends[provider]
        except KeyError as exc:
            raise ValueError(f"unsupported storage provider: {provider}") from exc
