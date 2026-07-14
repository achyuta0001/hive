"""
Notion connector.

Auto-discovers every page and database shared with the integration token
(no folder/path concept, unlike markdown_fs.py — Notion has no filesystem).
Walks database rows and nested child pages recursively, converts common
block types to plain text, and yields canonical Documents. Container pages
with no content of their own (only nested child pages) are skipped.

Auth: reads NOTION_API_KEY from the environment.
"""

from __future__ import annotations
import json
import os
import time
import urllib.request
from datetime import datetime

from core.canonical import Document

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Notion block types we know how to render as text, and how.
_LIST_ITEM_TYPES = {"bulleted_list_item", "numbered_list_item", "to_do"}
_TEXT_BLOCK_TYPES = {
    "paragraph", "quote", "heading_1", "heading_2", "heading_3",
    "code", *_LIST_ITEM_TYPES,
}


def _headers() -> dict:
    api_key = os.environ.get("NOTION_API_KEY")
    if not api_key:
        raise RuntimeError("NOTION_API_KEY is not set")
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _request(path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{NOTION_API}{path}", data=data, headers=_headers(), method=method
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def _plain_text(rich_text: list[dict]) -> str:
    return "".join(part.get("plain_text", "") for part in rich_text)


def _block_to_line(block: dict) -> str | None:
    """Render one Notion block as a line of text, or None if unsupported/empty."""
    block_type = block.get("type")
    if block_type == "divider":
        return "---"
    if block_type not in _TEXT_BLOCK_TYPES:
        return None

    text = _plain_text(block[block_type].get("rich_text", []))
    if not text:
        return None

    if block_type == "heading_1":
        return f"# {text}"
    if block_type == "heading_2":
        return f"## {text}"
    if block_type == "heading_3":
        return f"### {text}"
    if block_type == "quote":
        return f"> {text}"
    if block_type == "bulleted_list_item":
        return f"- {text}"
    if block_type == "numbered_list_item":
        return f"1. {text}"
    if block_type == "to_do":
        checked = block[block_type].get("checked", False)
        return f"- [{'x' if checked else ' '}] {text}"
    if block_type == "code":
        return f"```\n{text}\n```"
    return text  # paragraph


def _get_children(block_id: str) -> list[dict]:
    results: list[dict] = []
    cursor = None
    while True:
        path = f"/blocks/{block_id}/children?page_size=100"
        if cursor:
            path += f"&start_cursor={cursor}"
        page = _request(path)
        results.extend(page.get("results", []))
        if not page.get("has_more"):
            return results
        cursor = page.get("next_cursor")


def _title_of(page: dict) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            title = _plain_text(prop.get("title", []))
            if title:
                return title
    return "Untitled"


def _walk_page(page_id: str, title: str, id_path: str, docs: list[Document]) -> None:
    """Recursively walk a page's blocks, emitting a Document per page with
    real content, and recursing into any nested child_page/child_database."""
    children = _get_children(page_id)

    text_lines: list[str] = []
    for block in children:
        block_type = block.get("type")

        if block_type == "child_page":
            child_title = block["child_page"]["title"]
            _walk_page(block["id"], child_title, f"{id_path}/{child_title}", docs)
            continue

        if block_type == "child_database":
            _walk_database(block["id"], id_path, docs)
            continue

        line = _block_to_line(block)
        if line is not None:
            text_lines.append(line)

    content = "\n\n".join(text_lines).strip()
    if not content:
        return  # container page with no content of its own — skip

    page = _request(f"/pages/{page_id}")
    docs.append(Document(
        id=id_path,
        source="notion",
        title=title,
        content=content,
        metadata={},
        permissions=["local"],
        links=[],
        source_url=page.get("url"),
        last_modified=_parse_time(page.get("last_edited_time")),
    ))


def _walk_database(database_id: str, id_path: str, docs: list[Document]) -> None:
    rows: list[dict] = []
    cursor = None
    while True:
        body = {"start_cursor": cursor} if cursor else {}
        page = _request(f"/databases/{database_id}/query", method="POST", body=body)
        rows.extend(page.get("results", []))
        if not page.get("has_more"):
            break
        cursor = page.get("next_cursor")

    for row in rows:
        row_title = _title_of(row)
        _walk_page(row["id"], row_title, f"{id_path}/{row_title}", docs)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def list_documents() -> list[Document]:
    """Discover every page/database shared directly with the integration
    token (i.e. explicitly connected via Notion's Connections UI, not just
    reachable through nesting) and return all pages with real content as
    canonical Documents. Recursion handles everything nested beneath a root."""
    docs: list[Document] = []
    cursor = None
    while True:
        body = {"start_cursor": cursor} if cursor else {}
        page = _request("/search", method="POST", body=body)
        for item in page.get("results", []):
            if item.get("parent", {}).get("type") != "workspace":
                continue  # reachable via recursion from a root, not itself a root
            if item["object"] == "database":
                title = _plain_text(item.get("title", []))
                _walk_database(item["id"], title, docs)
            elif item["object"] == "page":
                title = _title_of(item)
                _walk_page(item["id"], title, title, docs)
        if not page.get("has_more"):
            break
        cursor = page.get("next_cursor")
        time.sleep(0.34)  # stay under Notion's ~3 req/s rate limit

    return docs
