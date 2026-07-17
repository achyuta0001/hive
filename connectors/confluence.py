"""
Confluence connector (Cloud only, not Server/Data Center).

Auto-discovers every space the API token can see, lists all pages per
space (storage-format bodies), converts the XHTML storage format to
markdown-ish text, and yields canonical Documents. Pages whose converted
body is empty (pure containers) are skipped, mirroring the Notion
connector's rule.

First connector to capture real ACLs under the capture-only permissions
layer: per-page read restrictions become `confluence:user:<accountId>` /
`confluence:group:<name>` entries; a page with no restrictions of its
own inherits its space's permissions and is recorded with the honest
scope `confluence:space:<spaceKey>` — never a fake "local", never empty.

API note: v2 (/wiki/api/v2/...) covers spaces and pages with cursor
pagination; restrictions exist only in v1 (/wiki/rest/api/...) — each v1
call below is marked. Auth is basic auth from CONFLUENCE_BASE_URL,
CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN.

NOT YET VALIDATED against a live Confluence site — built against API
docs with offline fixture tests (see the design spec). Treat the first
real-site run as part of the verification loop.
"""

from __future__ import annotations
import base64
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser

from core.canonical import Document


def _base_url() -> str:
    url = os.environ.get("CONFLUENCE_BASE_URL")
    if not url:
        raise RuntimeError("CONFLUENCE_BASE_URL is not set")
    return url.rstrip("/")


def _headers() -> dict:
    email = os.environ.get("CONFLUENCE_EMAIL")
    token = os.environ.get("CONFLUENCE_API_TOKEN")
    if not email:
        raise RuntimeError("CONFLUENCE_EMAIL is not set")
    if not token:
        raise RuntimeError("CONFLUENCE_API_TOKEN is not set")
    credentials = base64.b64encode(f"{email}:{token}".encode()).decode()
    return {"Authorization": f"Basic {credentials}", "Accept": "application/json"}


def _get(path: str, params: dict | None = None) -> dict:
    """All HTTP goes through here — tests monkeypatch this one seam.

    `path` is either absolute (a `_links.next` cursor URL path, already
    query-encoded) or a plain API path to which `params` are appended.
    """
    url = f"{_base_url()}{path}"
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def _paginate(path: str, params: dict | None = None) -> list[dict]:
    """Follow v2 cursor pagination (`_links.next`) to exhaustion."""
    results: list[dict] = []
    body = _get(path, params)
    while True:
        results.extend(body.get("results", []))
        next_path = body.get("_links", {}).get("next")
        if not next_path:
            return results
        body = _get(next_path)


class _StorageFormatParser(HTMLParser):
    """Convert Confluence storage-format XHTML to markdown-ish text.

    Known structure becomes markdown (headings, lists, quotes, code
    macros, table rows); unknown macros/tags are stripped but their
    inner text is kept — content is never silently dropped.
    """

    _HEADINGS = {f"h{n}": "#" * n for n in range(1, 7)}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._text: list[str] = []
        self._list_stack: list[str] = []   # "ul" | "ol"
        self._in_quote = False
        # code-macro state: ac:structured-macro ac:name="code" wraps an
        # ac:parameter (language) and ac:plain-text-body (the code)
        self._in_code_macro = False
        self._in_code_body = False
        self._code_language = ""
        self._param_name = ""
        self._in_row = False
        self._row_cells: list[str] = []

    # -- text accumulation ------------------------------------------------

    def handle_data(self, data: str) -> None:
        if self._in_code_body:
            self._text.append(data)
        elif self._in_code_macro and self._param_name == "language":
            self._code_language += data.strip()
        elif data.strip():
            self._text.append(data)

    def _flush(self, prefix: str = "") -> None:
        text = "".join(self._text).strip()
        self._text = []
        if not text:
            return
        if self._in_quote:
            prefix = f"> {prefix}"
        self.lines.append(f"{prefix}{text}")

    # -- tags ---------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attributes = dict(attrs)
        if tag == "ac:structured-macro":
            if attributes.get("ac:name") == "code":
                self._in_code_macro = True
                self._code_language = ""
            # unknown macros: no state change — inner text still collected
        elif tag == "ac:parameter":
            self._param_name = attributes.get("ac:name", "")
        elif tag == "ac:plain-text-body" and self._in_code_macro:
            self._flush()
            self._in_code_body = True
        elif tag in ("ul", "ol"):
            self._flush()
            self._list_stack.append(tag)
        elif tag == "li":
            self._flush()
        elif tag == "blockquote":
            self._flush()
            self._in_quote = True
        elif tag == "tr":
            self._flush()
            self._in_row = True
            self._row_cells = []
        elif tag in ("td", "th") and self._in_row:
            self._text = []
        elif tag in self._HEADINGS or tag == "p":
            self._flush()
        elif tag == "br":
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag == "ac:structured-macro" and self._in_code_macro:
            self._in_code_macro = False
        elif tag == "ac:parameter":
            self._param_name = ""
        elif tag == "ac:plain-text-body" and self._in_code_body:
            code = "".join(self._text).rstrip()
            self._text = []
            self._in_code_body = False
            self.lines.append(f"```{self._code_language}\n{code}\n```")
        elif tag in self._HEADINGS:
            self._flush(f"{self._HEADINGS[tag]} ")
        elif tag == "p":
            self._flush()
        elif tag == "li":
            marker = "1." if self._list_stack and self._list_stack[-1] == "ol" else "-"
            self._flush(f"{marker} ")
        elif tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
        elif tag == "blockquote":
            self._flush()
            self._in_quote = False
        elif tag in ("td", "th") and self._in_row:
            self._row_cells.append("".join(self._text).strip())
            self._text = []
        elif tag == "tr" and self._in_row:
            self._in_row = False
            if any(self._row_cells):
                self.lines.append("| " + " | ".join(self._row_cells) + " |")

    def close(self) -> None:
        super().close()
        self._flush()


def storage_to_text(storage_html: str) -> str:
    parser = _StorageFormatParser()
    parser.feed(storage_html)
    parser.close()
    return "\n\n".join(parser.lines).strip()


def _page_permissions(page_id: str, space_key: str) -> list[str]:
    """Read restrictions → canonical entries; unrestricted → space scope.

    v1 endpoint — v2 has no restrictions equivalent (recheck someday).
    A fetch failure propagates: a page whose ACLs we couldn't read must
    not be recorded with broader-looking permissions than it may have.
    """
    body = _get(f"/wiki/rest/api/content/{page_id}/restriction")
    entries: list[str] = []
    for restriction in body.get("results", []):
        if restriction.get("operation") != "read":
            continue
        restricted = restriction.get("restrictions", {})
        for user in restricted.get("user", {}).get("results", []):
            if user.get("accountId"):
                entries.append(f"confluence:user:{user['accountId']}")
        for group in restricted.get("group", {}).get("results", []):
            if group.get("name"):
                entries.append(f"confluence:group:{group['name']}")
    return entries or [f"confluence:space:{space_key}"]


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _path_id(page: dict, pages_by_id: dict[str, dict], space_name: str) -> str:
    """Path-style id from the parent chain: 'Space/Parent Title/Title'."""
    chain = [page["title"]]
    seen = {page["id"]}
    parent_id = page.get("parentId")
    while parent_id and parent_id in pages_by_id and parent_id not in seen:
        parent = pages_by_id[parent_id]
        chain.append(parent["title"])
        seen.add(parent["id"])
        parent_id = parent.get("parentId")
    return "/".join([space_name, *reversed(chain)])


def list_documents() -> list[Document]:
    """Discover every space the token can see and ingest all its pages."""
    docs: list[Document] = []
    spaces = _paginate("/wiki/api/v2/spaces")

    for space in spaces:
        space_key = space.get("key", str(space["id"]))
        space_name = space.get("name", space_key)
        pages = _paginate(
            "/wiki/api/v2/pages",
            {"space-id": space["id"], "body-format": "storage"},
        )
        pages_by_id = {p["id"]: p for p in pages}

        for page in pages:
            storage = page.get("body", {}).get("storage", {}).get("value", "")
            content = storage_to_text(storage)
            if not content.strip():
                continue  # pure container page, mirrors the Notion rule

            version = page.get("version", {}) or {}
            webui = page.get("_links", {}).get("webui")
            docs.append(Document(
                id=_path_id(page, pages_by_id, space_name),
                source="confluence",
                title=page["title"],
                content=content,
                metadata={
                    "space_key": space_key,
                    "page_id": page["id"],
                    "version": version.get("number"),
                    "author": version.get("authorId"),
                },
                permissions=_page_permissions(page["id"], space_key),
                source_url=f"{_base_url()}/wiki{webui}" if webui else None,
                last_modified=_parse_timestamp(version.get("createdAt")),
            ))
    return docs
