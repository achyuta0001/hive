"""
Offline tests for connectors/notion.py — no network, no NOTION_API_KEY.

All HTTP is stubbed by monkeypatching connectors.notion._request, the
single seam every request goes through. Fixtures mirror real Notion API
response shapes (search results, block children, page objects).

Run: python -m pytest tests/test_notion.py  (or python tests/test_notion.py)
"""

from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import connectors.notion as notion
from connectors.notion import _block_to_line, _plain_text, _title_of
from core.permissions import validate_permissions


# --- block rendering ------------------------------------------------------

def _rich(text: str) -> list[dict]:
    return [{"plain_text": text}]


def test_plain_text_concatenates_parts():
    assert _plain_text([{"plain_text": "a"}, {"plain_text": "b"}]) == "ab"


def test_headings_and_paragraph():
    assert _block_to_line({"type": "heading_1", "heading_1": {"rich_text": _rich("T")}}) == "# T"
    assert _block_to_line({"type": "heading_2", "heading_2": {"rich_text": _rich("T")}}) == "## T"
    assert _block_to_line({"type": "heading_3", "heading_3": {"rich_text": _rich("T")}}) == "### T"
    assert _block_to_line({"type": "paragraph", "paragraph": {"rich_text": _rich("body")}}) == "body"


def test_quote_and_lists():
    assert _block_to_line({"type": "quote", "quote": {"rich_text": _rich("w")}}) == "> w"
    assert _block_to_line({"type": "bulleted_list_item",
                           "bulleted_list_item": {"rich_text": _rich("x")}}) == "- x"
    assert _block_to_line({"type": "numbered_list_item",
                           "numbered_list_item": {"rich_text": _rich("y")}}) == "1. y"


def test_todo_checked_states():
    done = {"type": "to_do", "to_do": {"rich_text": _rich("ship"), "checked": True}}
    open_ = {"type": "to_do", "to_do": {"rich_text": _rich("ship"), "checked": False}}
    assert _block_to_line(done) == "- [x] ship"
    assert _block_to_line(open_) == "- [ ] ship"


def test_code_and_divider():
    code = {"type": "code", "code": {"rich_text": _rich('print("hi")')}}
    assert _block_to_line(code) == '```\nprint("hi")\n```'
    assert _block_to_line({"type": "divider", "divider": {}}) == "---"


def test_unsupported_and_empty_blocks_render_none():
    assert _block_to_line({"type": "image", "image": {}}) is None
    assert _block_to_line({"type": "paragraph", "paragraph": {"rich_text": []}}) is None


def test_title_of_falls_back_to_untitled():
    page = {"properties": {"Name": {"type": "title", "title": _rich("My Page")}}}
    assert _title_of(page) == "My Page"
    assert _title_of({"properties": {}}) == "Untitled"


# --- discovery walk (monkeypatched _request) ------------------------------

def _search_page(page_id: str, title: str, parent_type: str) -> dict:
    return {
        "object": "page",
        "id": page_id,
        "parent": {"type": parent_type},
        "properties": {"title": {"type": "title", "title": _rich(title)}},
    }


def _paragraph(text: str) -> dict:
    return {"type": "paragraph", "paragraph": {"rich_text": _rich(text)}}


def _run_with_responses(responses: dict):
    """Monkeypatch notion._request with a canned path-prefix dispatcher."""
    def fake_request(path: str, method: str = "GET", body: dict | None = None) -> dict:
        for prefix, payload in responses.items():
            if path.startswith(prefix):
                return payload
        raise AssertionError(f"unexpected request: {method} {path}")

    original = notion._request
    notion._request = fake_request
    try:
        return notion.list_documents()
    finally:
        notion._request = original


def test_walk_skips_non_workspace_roots_and_container_pages():
    # Search returns a workspace root plus a nested page (parent=page_id) —
    # the nested one must be reached via recursion, never treated as a root
    # (the live-workspace duplication bug this connector already hit once).
    docs = _run_with_responses({
        "/search": {"results": [
            _search_page("root1", "Root", "workspace"),
            _search_page("child1", "Child", "page_id"),
        ], "has_more": False},
        # Root is a pure container: only a child_page block, no content.
        "/blocks/root1/children": {"results": [
            {"type": "child_page", "id": "child1", "child_page": {"title": "Child"}},
        ], "has_more": False},
        "/blocks/child1/children": {"results": [_paragraph("Child body")], "has_more": False},
        "/pages/child1": {"url": "https://notion.so/child1",
                          "last_edited_time": "2026-07-01T10:00:00Z"},
    })
    assert len(docs) == 1  # container root skipped, nested search hit skipped
    doc = docs[0]
    assert doc.id == "Root/Child"          # path-style id from the title chain
    assert doc.source == "notion"
    assert doc.content == "Child body"
    assert doc.source_url == "https://notion.so/child1"
    assert doc.last_modified is not None
    assert doc.permissions == ["notion:integration:workspace"]
    validate_permissions(doc)  # honest scope must pass the connector contract


def test_walk_emits_parent_with_own_content_too():
    docs = _run_with_responses({
        "/search": {"results": [_search_page("root1", "Root", "workspace")],
                    "has_more": False},
        "/blocks/root1/children": {"results": [
            _paragraph("Root intro"),
            {"type": "child_page", "id": "child1", "child_page": {"title": "Child"}},
        ], "has_more": False},
        "/blocks/child1/children": {"results": [_paragraph("Child body")], "has_more": False},
        "/pages/root1": {"url": None, "last_edited_time": None},
        "/pages/child1": {"url": None, "last_edited_time": None},
    })
    assert sorted(d.id for d in docs) == ["Root", "Root/Child"]
    root = next(d for d in docs if d.id == "Root")
    assert root.content == "Root intro"


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
