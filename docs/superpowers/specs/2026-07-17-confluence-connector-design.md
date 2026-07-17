# Confluence Connector — Design

Date: 2026-07-17 · Status: approved

## Goal

Third connector: ingest Confluence Cloud pages as canonical `Document`s,
capturing real ACLs via the capture-only permissions layer (the first
connector to do so). Built offline against Atlassian Cloud REST API docs
with fixture-based tests; **live validation is an explicit open item**
until a Confluence site exists (free-tier signup works).

## Decisions (user-approved)

- **Confluence Cloud only** (not Server/Data Center). Basic auth:
  `CONFLUENCE_BASE_URL` (e.g. `https://yoursite.atlassian.net`),
  `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`. stdlib `urllib`.
- **Offline-first build.** All HTTP through one `_get(path, params)`
  helper — the seam tests monkeypatch. No live validation before PR.
- **v1/v2 API split handled explicitly.** v2 (`/wiki/api/v2/...`) for
  spaces and pages (cursor pagination). v1
  (`/wiki/rest/api/content/{id}/restriction`) only for read
  restrictions — v2 has no restrictions endpoint; each v1 call carries a
  comment saying so.

## `connectors/confluence.py`

### Discovery

`list_documents()` — no folder arg (mirrors Notion):

1. `GET /wiki/api/v2/spaces` — every space the token can see.
2. Per space: `GET /wiki/api/v2/pages?space-id=...&body-format=storage`,
   following cursor pagination (`Link` header / `_links.next`).
3. Hierarchy rebuilt from each page's `parentId` to produce path-style
   ids: `"Space Name/Parent Title/Page Title"` — mirrors
   `markdown_fs.py` (file paths) and `notion.py` (title chains).
   No Notion-style root-vs-nested duplication trap: the pages endpoint
   is flat.

### Content conversion (storage format → markdown-ish text)

Storage format is XHTML. A stdlib `html.parser.HTMLParser` subclass
converts: `h1–h6` → `#`-headings, `p` → paragraphs, `ul`/`ol`/`li` →
list items, `blockquote` → `>`, `ac:structured-macro` with
`ac:name="code"` → fenced code block (language parameter preserved),
tables → simple pipe rows, links → their text. Unknown macros/tags:
strip markup, keep inner text — never silently drop content. Pages whose
converted body is empty/whitespace are skipped (mirrors Notion's
container-page rule).

### Permissions (first real ACL capture)

Per page: `GET /wiki/rest/api/content/{page_id}/restriction` (v1).
Read-restriction users → `confluence:user:<accountId>`, groups →
`confluence:group:<group name>`. Empty read restrictions mean the page
inherits space permissions → honest scope
`["confluence:space:<spaceKey>"]`. `permissions` is therefore never
empty (passes `validate_permissions`) and never a fake `"local"`.

### Document mapping

- `id`: path-style title chain (above).
- `source`: `"confluence"`.
- `title`: page title.
- `content`: converted markdown-ish text.
- `metadata`: space key, page id, version number, author accountId when
  present.
- `source_url`: `_links.webui` joined onto the base URL.
- `last_modified`: page `version.createdAt`.

### Error handling

- Missing env vars → `RuntimeError` naming the variable (matches
  compiler/embeddings style).
- Restriction fetch failure for one page → raise; do not silently fall
  back to space scope (a page whose ACLs we couldn't read must not be
  recorded with broader-looking permissions than it may have).

## Wiring

`main.py`: `--source confluence` choice; calls
`confluence.list_documents()`. Nothing below the canonical layer
changes — zero edits to `core/`.

## Tests — `tests/test_confluence.py` (offline, no network)

Fixture JSON shaped like real API responses; `_get` monkeypatched.
Cases:

- storage→markdown: headings, lists, code macro with language, unknown
  macro keeps text, table rows.
- restriction mapping: users → `confluence:user:*`, groups →
  `confluence:group:*`, empty → `["confluence:space:<key>"]`.
- cursor pagination: two pages of results stitched.
- path-style id with nested parent chain.
- empty-body page skipped.
- every emitted doc passes `core.permissions.validate_permissions`.

Follows `tests/test_precheck.py` conventions (plain asserts,
`__main__` runner, no pytest required).

## Known gap (explicit)

Built against API documentation, not a live site. The Notion connector's
worst bug (duplication) only surfaced live. CLAUDE.md will flag the
connector as **not yet validated against a real Confluence site** until
that happens.
