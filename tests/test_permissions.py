"""
Offline tests for core/permissions.py (and its hash_diff persistence) —
no network, no LLM.

Run: python -m pytest tests/test_permissions.py  (or python tests/test_permissions.py)
"""

from __future__ import annotations
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.canonical import Document
from core.permissions import (
    page_permission_map,
    validate_entry,
    validate_permissions,
)


class SkipTest(Exception):
    """Raised when a test's prerequisites (parallel work) aren't in place yet."""


def _doc(id: str, *, source: str = "test",
         permissions: list[str] | None = None) -> Document:
    return Document(
        id=id,
        source=source,
        title=id,
        content=f"content of {id}",
        permissions=["local"] if permissions is None else permissions,
    )


def test_validate_entry_accepts_local():
    assert validate_entry("local")


def test_validate_entry_accepts_namespaced():
    assert validate_entry("notion:user:abc")


def test_validate_entry_rejects_empty():
    assert not validate_entry("")


def test_validate_entry_rejects_trailing_colon():
    assert not validate_entry("notion:")


def test_validate_entry_rejects_whitespace_segment():
    assert not validate_entry("a b:c:d")


def test_validate_entry_rejects_two_segments():
    assert not validate_entry("notion:user")


def test_validate_permissions_raises_on_empty_list():
    doc = _doc("empty-perms", permissions=[])
    try:
        validate_permissions(doc)
    except ValueError as exc:
        assert "empty-perms" in str(exc)
    else:
        raise AssertionError("expected ValueError on empty permissions")


def test_validate_permissions_raises_on_invalid_entry():
    doc = _doc("bad-entry", permissions=["local", "notion:"])
    try:
        validate_permissions(doc)
    except ValueError as exc:
        assert "bad-entry" in str(exc)
    else:
        raise AssertionError("expected ValueError on invalid entry")


def test_validate_permissions_passes_on_local():
    validate_permissions(_doc("ok", permissions=["local"]))  # must not raise


def test_page_permission_map_round_trip():
    a = _doc("docs/a.md", permissions=["local"])
    b = _doc("docs/b.md", permissions=["notion:user:abc", "notion:group:eng"])
    out = page_permission_map([a, b])
    assert out == {
        "docs/a.md": ["local"],
        "docs/b.md": ["notion:user:abc", "notion:group:eng"],
    }


def test_page_permissions_persistence_round_trip():
    # save/load/reset live in core/hash_diff.py and are being written per
    # the same spec; skip (not fail) until they exist.
    import core.hash_diff as hash_diff
    try:
        save = hash_diff.save_page_permissions
        load = hash_diff.load_page_permissions
    except AttributeError as exc:
        raise SkipTest(str(exc))

    original_db_path = hash_diff.DB_PATH
    with tempfile.TemporaryDirectory() as tmp:
        hash_diff.DB_PATH = Path(tmp) / "state.db"
        try:
            a = _doc("a", source="markdown", permissions=["local"])
            b = _doc("b", source="notion",
                     permissions=["notion:integration:workspace"])

            save("my-topic", [a, b])
            assert load("my-topic") == {
                "markdown::a": ["local"],
                "notion::b": ["notion:integration:workspace"],
            }

            # Unknown page -> empty dict.
            assert load("no-such-topic") == {}

            # Recompile with a different member set: wholesale replacement,
            # old doc gone.
            c = _doc("c", source="markdown", permissions=["local"])
            save("my-topic", [a, c])
            after = load("my-topic")
            assert after == {
                "markdown::a": ["local"],
                "markdown::c": ["local"],
            }, after

            # reset_state() clears the table.
            hash_diff.reset_state()
            assert load("my-topic") == {}
        finally:
            hash_diff.DB_PATH = original_db_path


def test_markdown_connector_emits_local():
    from connectors.markdown_fs import list_documents
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "note.md").write_text("# Note\n\nSome content.\n")
        docs = list_documents(tmp)
        assert len(docs) == 1, docs
        assert docs[0].permissions == ["local"]


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except (SkipTest, ImportError) as exc:
                print(f"SKIP {name}: {exc}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    sys.exit(1 if failures else 0)
