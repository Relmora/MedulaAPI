"""Provider-neutral object-storage failures."""


class ObjectVersionMismatchError(RuntimeError):
    """The requested immutable object version is no longer available."""
