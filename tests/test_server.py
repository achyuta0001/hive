"""
Offline tests for server/app.py's read endpoints — no network, no LLM.

Calls the endpoint functions directly (the same functions mcp_server.py
wraps), with WIKI_DIR pointed at a temp folder and the SQLite state DB
swapped for a temp file. POST /check-conflicts is excluded: it requires a
live LLM provider and is covered by the manual verification loop.

Run: python -m pytest tests/test_server.py  (or python tests/test_server.py)
"""

from __future__ import annotations
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.hash_diff as hash_diff
import server.app as server_app
from core.canonical import Document
from core.hash_diff import record_sync_stats, save_page_permissions
from fastapi import HTTPException


def _with_temp_state(fn):
    original_db, original_wiki = hash_diff.DB_PATH, server_app.WIKI_DIR
    with tempfile.TemporaryDirectory() as tmp:
        hash_diff.DB_PATH = Path(tmp) / "state.db"
        server_app.WIKI_DIR = Path(tmp) / "wiki"
        server_app.WIKI_DIR.mkdir()
        try:
            fn()
        finally:
            hash_diff.DB_PATH, server_app.WIKI_DIR = original_db, original_wiki


def _doc(doc_id: str, permissions: list[str]) -> Document:
    return Document(id=doc_id, source="markdown", title=doc_id,
                    content="x", permissions=permissions)


def test_get_wiki_page_404_when_missing():
    def check():
        try:
            server_app.get_wiki_page("nope")
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 404
    _with_temp_state(check)


def test_get_wiki_page_returns_content_and_permission_map():
    def check():
        (server_app.WIKI_DIR / "deploy.md").write_text("# Deploy\n", encoding="utf-8")
        save_page_permissions("deploy", [_doc("a.md", ["local"])])
        page = server_app.get_wiki_page("deploy")
        assert page["content"] == "# Deploy\n"
        assert page["permissions"] == {"markdown::a.md": ["local"]}
        assert page["restricted"] is False  # all-local sources
    _with_temp_state(check)


def test_restricted_true_for_non_local_sources():
    def check():
        (server_app.WIKI_DIR / "notes.md").write_text("n", encoding="utf-8")
        save_page_permissions("notes", [
            _doc("a.md", ["local"]),
            Document(id="p", source="notion", title="p", content="y",
                     permissions=["notion:integration:workspace"]),
        ])
        assert server_app.get_wiki_page("notes")["restricted"] is True
    _with_temp_state(check)


def test_list_wiki_pages_sorted_stems():
    def check():
        for name in ("zeta", "alpha"):
            (server_app.WIKI_DIR / f"{name}.md").write_text("x", encoding="utf-8")
        assert server_app.list_wiki_pages() == {"topics": ["alpha", "zeta"]}
    _with_temp_state(check)


def test_list_wiki_pages_missing_dir():
    def check():
        server_app.WIKI_DIR.rmdir()
        assert server_app.list_wiki_pages() == {"topics": []}
    _with_temp_state(check)


def test_get_stats_passthrough():
    def check():
        record_sync_stats(4, 3, 1200)
        stats = server_app.get_stats()
        assert stats["runs"] == 1
        assert stats["docs_skipped_total"] == 3
        assert stats["tokens_saved_estimate_total"] == 1200
    _with_temp_state(check)


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
