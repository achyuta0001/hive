"""
Capture-only permissions layer: canonical validation of Document.permissions.

Nothing here enforces access — there is one user. The point is that every
connector must *capture* its source's ACLs into a canonical, opaque form
now, so that when enforcement is bolted onto the serving layer later, the
full per-doc permission data is already on record. Entries are either the
bare "local" or namespaced opaque strings "<namespace>:<type>:<value>"
(e.g. "notion:user:abc123", "confluence:group:engineering"); downstream
code compares them by string equality only and never parses them apart.

Source-agnostic by design: operates purely on canonical Document fields,
never branches on doc.source.
"""

from __future__ import annotations

from core.canonical import Document


def validate_entry(entry: str) -> bool:
    """True iff entry is bare "local" or a well-formed namespace:type:value.

    Each of the three colon-separated segments must be non-empty and
    contain no whitespace. Anything else is invalid.
    """
    if entry == "local":
        return True
    parts = entry.split(":")
    if len(parts) != 3:
        return False
    return all(seg and not any(ch.isspace() for ch in seg) for seg in parts)


def validate_permissions(doc: Document) -> None:
    """Raise ValueError (naming the doc) if its permissions are missing/bad.

    Called on ingested docs before hash-diff, so a connector that forgets
    to populate permissions fails loudly, not silently.
    """
    if not doc.permissions:
        raise ValueError(
            f"Document '{doc.id}' has no permission entries; every "
            f"connector must capture permissions (capture-only layer)."
        )
    for entry in doc.permissions:
        if not validate_entry(entry):
            raise ValueError(
                f"Document '{doc.id}' has invalid permission entry "
                f"{entry!r}; expected 'local' or 'namespace:type:value'."
            )


def page_permission_map(docs: list[Document]) -> dict[str, list[str]]:
    """Full per-source map for a compiled page: {doc.id: doc.permissions}."""
    return {doc.id: doc.permissions for doc in docs}
