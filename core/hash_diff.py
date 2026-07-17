"""
Hash-diff: tracks a content hash per document in SQLite, so every sync
only processes documents that are new or have actually changed.

This is the single biggest cost lever in the whole pipeline - everything
downstream (embeddings, LLM calls) only ever sees what comes out of here.
"""

from __future__ import annotations
import hashlib
import json
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS doc_embedding (
            source TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            vector TEXT NOT NULL,
            PRIMARY KEY (source, doc_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT DEFAULT CURRENT_TIMESTAMP,
            docs_total INTEGER NOT NULL,
            docs_skipped INTEGER NOT NULL,
            tokens_saved_estimate INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS page_permission (
            topic_slug TEXT NOT NULL,
            source TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            permissions TEXT NOT NULL,
            PRIMARY KEY (topic_slug, source, doc_id)
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


def save_embeddings(docs: list[Document], vectors: dict[str, list[float]]) -> None:
    """
    Persist embedding vectors keyed by "<source>::<id>", stamped with the
    content hash they were computed from, so stale vectors are detectable.
    """
    conn = _connect()
    for doc in docs:
        key = f"{doc.source}::{doc.id}"
        if key not in vectors:
            continue
        content_hash = doc.content_hash or _hash_content(doc.content)
        conn.execute(
            """
            INSERT INTO doc_embedding (source, doc_id, content_hash, vector)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source, doc_id) DO UPDATE SET
                content_hash = excluded.content_hash,
                vector = excluded.vector
            """,
            (doc.source, doc.id, content_hash, json.dumps(vectors[key])),
        )
    conn.commit()
    conn.close()


def load_embeddings(docs: list[Document]) -> dict[str, list[float]]:
    """
    Load stored embeddings for the given docs. A vector is only returned if
    its stored content hash matches the doc's current content - stale or
    missing rows are silently omitted (caller should re-embed those).
    """
    conn = _connect()
    result: dict[str, list[float]] = {}
    for doc in docs:
        row = conn.execute(
            "SELECT content_hash, vector FROM doc_embedding WHERE source = ? AND doc_id = ?",
            (doc.source, doc.id),
        ).fetchone()
        if row is None:
            continue
        current_hash = doc.content_hash or _hash_content(doc.content)
        if row[0] == current_hash:
            result[f"{doc.source}::{doc.id}"] = json.loads(row[1])
    conn.close()
    return result


def save_page_permissions(topic_slug: str, docs: list[Document]) -> None:
    """
    Record which source docs (and their ACLs) a compiled page was built from,
    one row per member doc with permissions stored as a JSON list. Capture-only,
    no enforcement - existing rows for the slug are replaced wholesale.
    """
    conn = _connect()
    conn.execute("DELETE FROM page_permission WHERE topic_slug = ?", (topic_slug,))
    for doc in docs:
        conn.execute(
            """
            INSERT INTO page_permission (topic_slug, source, doc_id, permissions)
            VALUES (?, ?, ?, ?)
            """,
            (topic_slug, doc.source, doc.id, json.dumps(doc.permissions)),
        )
    conn.commit()
    conn.close()


def load_page_permissions(topic_slug: str) -> dict[str, list[str]]:
    """
    Load the recorded per-doc permissions for a compiled page, keyed
    "<source>::<doc_id>". Returns an empty dict if the slug is unknown.
    """
    conn = _connect()
    result: dict[str, list[str]] = {}
    for source, doc_id, permissions in conn.execute(
        "SELECT source, doc_id, permissions FROM page_permission WHERE topic_slug = ?",
        (topic_slug,),
    ):
        result[f"{source}::{doc_id}"] = json.loads(permissions)
    conn.close()
    return result


def record_sync_stats(docs_total: int, docs_skipped: int, tokens_saved_estimate: int) -> None:
    """
    Record one sync run's cost-gate outcome: how many docs the hash-diff
    filter kept away from embeddings/LLM calls, and a rough token estimate
    (chars/4) of what that skipped content would have cost to reprocess.
    This is the built-in "what Hive saved you" number - honest because it
    is measured at the gate, not modeled.
    """
    conn = _connect()
    conn.execute(
        """
        INSERT INTO sync_stats (docs_total, docs_skipped, tokens_saved_estimate)
        VALUES (?, ?, ?)
        """,
        (docs_total, docs_skipped, tokens_saved_estimate),
    )
    conn.commit()
    conn.close()


def load_sync_stats() -> dict:
    """Cumulative cost-gate totals across all recorded sync runs."""
    conn = _connect()
    runs, skipped, saved = conn.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(docs_skipped), 0),
               COALESCE(SUM(tokens_saved_estimate), 0)
        FROM sync_stats
        """
    ).fetchone()
    conn.close()
    return {
        "runs": runs,
        "docs_skipped_total": skipped,
        "tokens_saved_estimate_total": saved,
    }


def reset_state() -> None:
    """Wipe all tracked state - useful for testing the pipeline from scratch."""
    conn = _connect()
    conn.execute("DELETE FROM doc_state")
    conn.execute("DELETE FROM doc_embedding")
    conn.execute("DELETE FROM page_permission")
    conn.execute("DELETE FROM sync_stats")
    conn.commit()
    conn.close()
