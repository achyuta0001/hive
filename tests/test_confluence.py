"""
Offline tests for connectors/confluence.py — no network.

All HTTP is stubbed by monkeypatching connectors.confluence._get, the
single seam every request goes through. Fixtures mirror real Atlassian
Cloud API response shapes.

Run: python -m pytest tests/test_confluence.py  (or python tests/test_confluence.py)
"""

from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import connectors.confluence as confluence
from connectors.confluence import storage_to_text
from core.permissions import validate_permissions


# --- storage-format conversion ------------------------------------------

def test_storage_headings_and_paragraphs():
    text = storage_to_text("<h1>Title</h1><p>Body text.</p><h3>Sub</h3>")
    assert "# Title" in text
    assert "Body text." in text
    assert "### Sub" in text


def test_storage_lists():
    text = storage_to_text("<ul><li>alpha</li><li>beta</li></ul><ol><li>first</li></ol>")
    assert "- alpha" in text
    assert "- beta" in text
    assert "1. first" in text


def test_storage_code_macro_with_language():
    xml = ('<ac:structured-macro ac:name="code">'
           '<ac:parameter ac:name="language">python</ac:parameter>'
           '<ac:plain-text-body>print("hi")</ac:plain-text-body>'
           '</ac:structured-macro>')
    text = storage_to_text(xml)
    assert '```python\nprint("hi")\n```' in text


def test_storage_unknown_macro_keeps_text():
    xml = ('<ac:structured-macro ac:name="mystery-widget">'
           '<p>important fact inside</p></ac:structured-macro>')
    assert "important fact inside" in storage_to_text(xml)


def test_storage_table_rows():
    xml = ("<table><tr><th>Key</th><th>Value</th></tr>"
           "<tr><td>timeout</td><td>30</td></tr></table>")
    text = storage_to_text(xml)
    assert "| Key | Value |" in text
    assert "| timeout | 30 |" in text


def test_storage_blockquote():
    assert "> wisdom" in storage_to_text("<blockquote><p>wisdom</p></blockquote>")


# --- fixtures for the API walk -------------------------------------------

def _space(space_id="s1", key="ENG", name="Engineering"):
    return {"id": space_id, "key": key, "name": name}


def _page(page_id, title, body="<p>content</p>", parent_id=None):
    return {
        "id": page_id,
        "title": title,
        "parentId": parent_id,
        "body": {"storage": {"value": body}},
        "version": {"number": 3, "authorId": "acct-1",
                    "createdAt": "2026-07-01T10:00:00Z"},
        "_links": {"webui": f"/spaces/ENG/pages/{page_id}"},
    }


def _no_restrictions():
    return {"results": [
        {"operation": "read",
         "restrictions": {"user": {"results": []}, "group": {"results": []}}},
    ]}


def _fake_get(responses):
    """Return a _get stub serving canned responses keyed by path prefix."""
    def fake(path, params=None):
        for prefix, response in responses.items():
            if path.startswith(prefix):
                if callable(response):
                    return response(path, params)
                return response
        raise AssertionError(f"unexpected request: {path} {params}")
    return fake


def _run_list_documents(monkey_get):
    original = confluence._get
    confluence._get = monkey_get
    # base URL only used for source_url formatting
    import os
    original_env = os.environ.get("CONFLUENCE_BASE_URL")
    os.environ["CONFLUENCE_BASE_URL"] = "https://example.atlassian.net"
    try:
        return confluence.list_documents()
    finally:
        confluence._get = original
        if original_env is None:
            del os.environ["CONFLUENCE_BASE_URL"]
        else:
            os.environ["CONFLUENCE_BASE_URL"] = original_env


# --- discovery / mapping ---------------------------------------------------

def test_basic_walk_and_document_mapping():
    docs = _run_list_documents(_fake_get({
        "/wiki/api/v2/spaces": {"results": [_space()], "_links": {}},
        "/wiki/api/v2/pages": {"results": [_page("p1", "Deploy Guide")], "_links": {}},
        "/wiki/rest/api/content/p1/restriction": _no_restrictions(),
    }))
    assert len(docs) == 1
    doc = docs[0]
    assert doc.source == "confluence"
    assert doc.id == "Engineering/Deploy Guide"
    assert "content" in doc.content
    assert doc.metadata["space_key"] == "ENG"
    assert doc.metadata["version"] == 3
    assert doc.source_url == "https://example.atlassian.net/wiki/spaces/ENG/pages/p1"
    assert doc.last_modified is not None and doc.last_modified.year == 2026
    validate_permissions(doc)


def test_unrestricted_page_gets_space_scope():
    docs = _run_list_documents(_fake_get({
        "/wiki/api/v2/spaces": {"results": [_space()], "_links": {}},
        "/wiki/api/v2/pages": {"results": [_page("p1", "Open Page")], "_links": {}},
        "/wiki/rest/api/content/p1/restriction": _no_restrictions(),
    }))
    assert docs[0].permissions == ["confluence:space:ENG"]


def test_restricted_page_maps_users_and_groups():
    restrictions = {"results": [
        {"operation": "read", "restrictions": {
            "user": {"results": [{"accountId": "abc123"}]},
            "group": {"results": [{"name": "engineering"}]},
        }},
        {"operation": "update", "restrictions": {   # must be ignored
            "user": {"results": [{"accountId": "ignored"}]},
            "group": {"results": []},
        }},
    ]}
    docs = _run_list_documents(_fake_get({
        "/wiki/api/v2/spaces": {"results": [_space()], "_links": {}},
        "/wiki/api/v2/pages": {"results": [_page("p1", "Secret Page")], "_links": {}},
        "/wiki/rest/api/content/p1/restriction": restrictions,
    }))
    assert docs[0].permissions == [
        "confluence:user:abc123", "confluence:group:engineering",
    ]
    validate_permissions(docs[0])


def test_cursor_pagination_stitched():
    first = {"results": [_page("p1", "One")],
             "_links": {"next": "/wiki/api/v2/pages?cursor=xyz"}}
    second = {"results": [_page("p2", "Two")], "_links": {}}

    def pages_response(path, params):
        return second if "cursor=xyz" in path else first

    docs = _run_list_documents(_fake_get({
        "/wiki/api/v2/spaces": {"results": [_space()], "_links": {}},
        "/wiki/api/v2/pages": pages_response,
        "/wiki/rest/api/content/p1/restriction": _no_restrictions(),
        "/wiki/rest/api/content/p2/restriction": _no_restrictions(),
    }))
    assert [d.title for d in docs] == ["One", "Two"]


def test_path_id_with_nested_parent_chain():
    pages = {"results": [
        _page("root", "Handbook"),
        _page("mid", "Onboarding", parent_id="root"),
        _page("leaf", "Laptop Setup", parent_id="mid"),
    ], "_links": {}}
    docs = _run_list_documents(_fake_get({
        "/wiki/api/v2/spaces": {"results": [_space()], "_links": {}},
        "/wiki/api/v2/pages": pages,
        "/wiki/rest/api/content/root/restriction": _no_restrictions(),
        "/wiki/rest/api/content/mid/restriction": _no_restrictions(),
        "/wiki/rest/api/content/leaf/restriction": _no_restrictions(),
    }))
    by_title = {d.title: d for d in docs}
    assert by_title["Laptop Setup"].id == "Engineering/Handbook/Onboarding/Laptop Setup"


def test_empty_body_page_skipped():
    docs = _run_list_documents(_fake_get({
        "/wiki/api/v2/spaces": {"results": [_space()], "_links": {}},
        "/wiki/api/v2/pages": {"results": [
            _page("p1", "Container", body=""),
            _page("p2", "Real Page"),
        ], "_links": {}},
        "/wiki/rest/api/content/p2/restriction": _no_restrictions(),
    }))
    assert [d.title for d in docs] == ["Real Page"]


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
