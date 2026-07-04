"""
Markdown/filesystem connector.

The simplest possible connector: walks a folder of .md files, parses
YAML frontmatter if present, and yields canonical Documents.

No auth, no rate limits, no API - this is why it's the first connector
to build. Every real connector (Notion, Confluence) just needs to produce
the same Document shape; nothing else in the pipeline changes.
"""

from __future__ import annotations
from datetime import datetime
from pathlib import Path

import frontmatter  # python-frontmatter

from core.canonical import Document


def list_documents(folder: str) -> list[Document]:
    """Walk `folder` recursively and return every .md file as a canonical Document."""
    root = Path(folder)
    docs: list[Document] = []

    for path in sorted(root.rglob("*.md")):
        post = frontmatter.load(path)
        title = post.metadata.get("title") or path.stem.replace("-", " ").title()
        mtime = datetime.fromtimestamp(path.stat().st_mtime)

        doc = Document(
            id=str(path.relative_to(root)),
            source="markdown",
            title=title,
            content=post.content.strip(),
            metadata=dict(post.metadata),
            permissions=["local"],   # everything is visible to you locally
            links=[],                # link extraction can come later
            source_url=str(path.resolve()),
            last_modified=mtime,
        )
        docs.append(doc)

    return docs


def fetch(folder: str, doc_id: str) -> Document | None:
    """Fetch a single document by its relative id, e.g. 'notes/roadmap.md'."""
    for doc in list_documents(folder):
        if doc.id == doc_id:
            return doc
    return None
