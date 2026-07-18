"""
Offline tests for core/hash_diff.py — the cost gate. Uses a temporary
SQLite DB (same DB_PATH-swap pattern as test_stats.py), no network.

Run: python -m pytest tests/test_hash_diff.py  (or python tests/test_hash_diff.py)
"""

from __future__ import annotations
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.hash_diff as hash_diff
from core.canonical import Document
from core.hash_diff import (
    filter_changed,
    load_embeddings,
    load_page_permissions,
    mark_synced,
    reset_state,
    save_embeddings,
    save_page_permissions,
)


def _with_temp_db(fn):
    original = hash_diff.DB_PATH
    with tempfile.TemporaryDirectory() as tmp:
        hash_diff.DB_PATH = Path(tmp) / "state.db"
        try:
            fn()
        finally:
            hash_diff.DB_PATH = original


def _doc(doc_id: str, content: str, permissions: list[str] | None = None) -> Document:
    return Document(
        id=doc_id, source="markdown", title=doc_id.title(), content=content,
        permissions=permissions or ["local"],
    )


def test_all_new_docs_are_changed_and_hashed():
    def check():
        docs = [_doc("a", "alpha"), _doc("b", "beta")]
        changed = filter_changed(docs)
        assert [d.id for d in changed] == ["a", "b"]
        assert all(d.content_hash for d in changed)
    _with_temp_db(check)


def test_synced_docs_skipped_until_content_changes():
    def check():
        docs = [_doc("a", "alpha"), _doc("b", "beta")]
        mark_synced(filter_changed(docs))
        assert filter_changed(docs) == []

        edited = [_doc("a", "alpha v2"), _doc("b", "beta")]
        assert [d.id for d in filter_changed(edited)] == ["a"]
    _with_temp_db(check)


def test_reset_state_makes_everything_new_again():
    def check():
        docs = [_doc("a", "alpha")]
        mark_synced(filter_changed(docs))
        reset_state()
        assert [d.id for d in filter_changed(docs)] == ["a"]
    _with_temp_db(check)


def test_embeddings_roundtrip():
    def check():
        docs = filter_changed([_doc("a", "alpha")])
        save_embeddings(docs, {"markdown::a": [0.1, 0.2]})
        assert load_embeddings(docs) == {"markdown::a": [0.1, 0.2]}
    _with_temp_db(check)


def test_stale_embedding_omitted_after_content_change():
    def check():
        docs = filter_changed([_doc("a", "alpha")])
        save_embeddings(docs, {"markdown::a": [0.1, 0.2]})
        edited = filter_changed([_doc("a", "alpha v2")])
        assert load_embeddings(edited) == {}  # hash mismatch → caller re-embeds
    _with_temp_db(check)


def test_embedding_missing_from_vectors_dict_not_saved():
    def check():
        docs = filter_changed([_doc("a", "alpha"), _doc("b", "beta")])
        save_embeddings(docs, {"markdown::a": [0.1]})
        assert set(load_embeddings(docs)) == {"markdown::a"}
    _with_temp_db(check)


def test_page_permissions_roundtrip_and_wholesale_replace():
    def check():
        save_page_permissions("topic", [_doc("a", "x"), _doc("b", "y", ["notion:integration:workspace"])])
        assert load_page_permissions("topic") == {
            "markdown::a": ["local"],
            "markdown::b": ["notion:integration:workspace"],
        }
        # Re-save with fewer docs: old rows for the slug must be gone.
        save_page_permissions("topic", [_doc("b", "y")])
        assert load_page_permissions("topic") == {"markdown::b": ["local"]}
    _with_temp_db(check)


def test_unknown_slug_returns_empty_permissions():
    def check():
        assert load_page_permissions("nope") == {}
    _with_temp_db(check)


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    sys.exit(1 if failures else 0)
