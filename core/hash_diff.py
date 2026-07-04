"""
Hash-diff: tracks a content hash per document in SQLite, so every sync
only processes documents that are new or have actually changed.

This is the single biggest cost lever in the whole pipeline - everything
downstream (embeddings, LLM calls) only ever sees what comes out of here.
"""

from __future__ import annotations
import hashlib
import sqlite3
from pathlib import Path

from core.canonical import Document

DB_PATH = Path(__file__).parent.parent / "data" / "state.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS doc_state (
            source TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            last_synced TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (source, doc_id)
        )
        """
    )
    conn.commit()
    return conn


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def filter_changed(docs: list[Document]) -> list[Document]:
    """
    Given a list of canonical Documents, return only the ones that are
    new or whose content has changed since the last recorded sync.
    Also stamps content_hash onto each returned Document.
    """
    conn = _connect()
    changed: list[Document] = []

    for doc in docs:
        doc.content_hash = _hash_content(doc.content)
        row = conn.execute(
            "SELECT content_hash FROM doc_state WHERE source = ? AND doc_id = ?",
            (doc.source, doc.id),
        ).fetchone()

        if row is None or row[0] != doc.content_hash:
            changed.append(doc)

    conn.close()
    return changed


def mark_synced(docs: list[Document]) -> None:
    """Call this after successfully compiling a batch of docs."""
    conn = _connect()
    for doc in docs:
        conn.execute(
            """
            INSERT INTO doc_state (source, doc_id, content_hash, last_synced)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(source, doc_id) DO UPDATE SET
                content_hash = excluded.content_hash,
                last_synced = excluded.last_synced
            """,
            (doc.source, doc.id, doc.content_hash),
        )
    conn.commit()
    conn.close()


def reset_state() -> None:
    """Wipe all tracked state - useful for testing the pipeline from scratch."""
    conn = _connect()
    conn.execute("DELETE FROM doc_state")
    conn.commit()
    conn.close()
