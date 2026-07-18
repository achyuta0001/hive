"""
Offline tests for connectors/markdown_fs.py — real temp files, no mocking.

Run: python -m pytest tests/test_markdown_fs.py  (or python tests/test_markdown_fs.py)
"""

from __future__ import annotations
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from connectors.markdown_fs import fetch, list_documents
from core.permissions import validate_permissions


def _with_folder(files: dict[str, str], fn):
    """Materialize {relative_path: content} in a temp dir, call fn(folder)."""
    with tempfile.TemporaryDirectory() as tmp:
        for rel, content in files.items():
            path = Path(tmp) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        fn(tmp)


def test_empty_folder():
    def check(folder):
        assert list_documents(folder) == []
    _with_folder({}, check)


def test_recursive_walk_ids_and_sorted_order():
    def check(folder):
        docs = list_documents(folder)
        assert [d.id for d in docs] == ["a.md", "nested/b.md", "nested/deep/c.md"]
        assert all(d.source == "markdown" for d in docs)
    _with_folder({
        "nested/b.md": "b body",
        "a.md": "a body",
        "nested/deep/c.md": "c body",
        "ignore.txt": "not markdown",
    }, check)


def test_frontmatter_title_and_metadata_captured():
    def check(folder):
        doc = list_documents(folder)[0]
        assert doc.title == "Real Title"
        assert doc.metadata.get("tags") == ["ops", "deploy"]
        assert doc.content == "Body only."  # frontmatter stripped from content
    _with_folder({
        "page.md": "---\ntitle: Real Title\ntags: [ops, deploy]\n---\n\nBody only.\n",
    }, check)


def test_fallback_title_from_stem():
    def check(folder):
        doc = list_documents(folder)[0]
        assert doc.title == "My Deploy Notes"
    _with_folder({"my-deploy-notes.md": "no frontmatter here"}, check)


def test_connector_contract_permissions_and_fields():
    def check(folder):
        doc = list_documents(folder)[0]
        assert doc.permissions == ["local"]
        validate_permissions(doc)  # must satisfy the ingest contract
        assert doc.content == "padded"  # stripped
        assert Path(doc.source_url).is_absolute()
        assert doc.last_modified is not None
        assert doc.content_hash is None  # stamped later by hash_diff, not here
    _with_folder({"x.md": "  padded  \n\n"}, check)


def test_fetch_by_relative_id():
    def check(folder):
        hit = fetch(folder, "notes/roadmap.md")
        assert hit is not None and hit.title == "Roadmap"
        assert fetch(folder, "missing.md") is None
    _with_folder({
        "notes/roadmap.md": "---\ntitle: Roadmap\n---\nplan",
        "other.md": "x",
    }, check)


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
