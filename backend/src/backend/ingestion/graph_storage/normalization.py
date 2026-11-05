"""Conservative deterministic keys for cross-chunk entity matching."""

import unicodedata

ORGANIZATION_SUFFIXES = {
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "limited",
    "llc",
    "ltd",
}


def normalize_entity_name(name: str, entity_type: str) -> str:
    """Return a stable comparison key without fuzzy or model-based matching."""

    unicode_name = unicodedata.normalize("NFKC", name).casefold()
    words = "".join(
        character if character.isalnum() else " " for character in unicode_name
    ).split()
    if entity_type.strip().upper() == "ORGANIZATION":
        while words and words[-1] in ORGANIZATION_SUFFIXES:
            words.pop()
    return "".join(words)
