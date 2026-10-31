"""Provider-neutral object-storage failures."""


class ObjectVersionMismatchError(RuntimeError):
    """The requested immutable object version is no longer available."""


class ObjectStorageUnavailableError(RuntimeError):
    """A temporary provider failure that can succeed when retried."""
