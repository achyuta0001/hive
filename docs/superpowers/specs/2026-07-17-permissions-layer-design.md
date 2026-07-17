# Permissions Layer (Capture-Only) — Design

Date: 2026-07-17 · Status: approved

## Goal

Make `Document.permissions` real so ACL-bearing connectors (Confluence,
real Notion ACLs) can be added without violating the "no ACL sources
before a permissions layer exists" invariant. First version is
**capture-only**: connectors capture ACLs into a canonical form, the
pipeline records them per compiled page, the serving layer exposes them
as metadata. Nothing enforces yet — there is one user. Enforcement bolts
onto the FastAPI layer later, with full per-doc data already recorded.

## Decisions (user-approved)

- **Threat model: capture-only.** No caller identity, no filtering.
- **Principal form: namespaced opaque strings.** `"local"` or
  `"<namespace>:<type>:<value>"` (e.g. `notion:user:abc123`,
  `confluence:group:engineering`). Downstream code compares by string
  equality only, never parses. Cross-source identity unification deferred.
- **Page ACLs: full per-source map.** A compiled page stores
  `{doc_id: [permission entries]}` for every member doc — no
  intersection/union policy baked in now.
- **Storage: SQLite `state.db`.** Wiki markdown stays clean (Copilot
  reads it as plain context).

## Components

### `core/permissions.py` (new)

- `validate_entry(entry: str) -> bool` — accepts bare `"local"` or
  `namespace:type:value` (each segment non-empty, no whitespace).
- `validate_permissions(doc: Document) -> None` — raises `ValueError`
  naming the doc if `permissions` is empty or any entry is invalid.
  Called on ingested docs in `main.py` before hash-diff, so a connector
  that forgets to populate permissions fails loudly, not silently.
- `page_permission_map(docs: list[Document]) -> dict[str, list[str]]` —
  `{doc.id: doc.permissions}` for recording against a compiled page.
- Source-agnostic: never branches on `doc.source`.

### `core/hash_diff.py` (changed — it owns the DB)

- New table:
  `page_permission (topic_slug TEXT, source TEXT, doc_id TEXT,
  permissions TEXT /*json*/, PRIMARY KEY (topic_slug, source, doc_id))`.
- `save_page_permissions(topic_slug, docs)` — deletes existing rows for
  the slug, inserts one row per member doc. Called after each successful
  `compile_docs` in `main.py` (both cluster and legacy `--topic` mode).
- `load_page_permissions(topic_slug) -> dict[str, list[str]]` — keyed
  `"<source>::<doc_id>"`, empty dict if page unknown.
- `reset_state()` also clears `page_permission`.

### Connectors

- `connectors/markdown_fs.py`: keeps `["local"]` — now a legitimate
  canonical entry, not a placeholder.
- `connectors/notion.py`: Notion's API does not expose per-page ACLs to
  internal integrations, so it emits the honest scope
  `["notion:integration:workspace"]` ("whatever the token can see").
  Documented limitation.
- Future `connectors/confluence.py`: restrictions API → real
  `confluence:user:*` / `confluence:group:*` entries. This layer is the
  prerequisite that unblocks it.

### `server/app.py` (changed)

- `GET /wiki/{topic_slug}` response gains:
  `"permissions": {"<source>::<doc_id>": [entries]}` and
  `"restricted": bool` (true iff any member doc's permissions differ
  from `["local"]`). MCP tool `hive_get_wiki_page` inherits this for
  free — same function behind both surfaces.
- `POST /check-conflicts` unchanged: scratch pages never persist
  permissions.

### `core/compiler.py` — NOT changed

No permission logic in the LLM path. SYSTEM_PROMPT and
`_validate_output` untouched.

## Enforcement (explicitly deferred)

When a second reader exists: a FastAPI dependency resolves caller →
principal set; policy (intersection vs per-section filtering) is chosen
then, with the full per-doc map already on record. Until then the
serving layer stays open, matching "don't add infra ahead of the need."

## Tests (offline, no network)

`tests/test_permissions.py`:
- validator accepts `local`, `notion:user:abc`; rejects empty string,
  `notion:`, `a b:c:d`, empty list.
- `page_permission_map` round-trip.
- `save_page_permissions`/`load_page_permissions` round-trip against a
  temp DB (monkeypatched `DB_PATH`), including wholesale replacement on
  recompile and `reset_state()` clearing.
- markdown connector emits `["local"]` on a temp folder.

## Verification

1. `python3 tests/test_permissions.py` (and existing
   `tests/test_precheck.py`) — all pass.
2. `python main.py --reset` — pipeline runs unchanged; then
   `GET /wiki/devops-notes` shows the permission map with `"local"`
   entries and `"restricted": false`.
3. `python main.py --source notion --topic notion-stress-test` —
   page permissions show `notion:integration:workspace`,
   `"restricted": true`. (Requires NOTION_API_KEY; skip if offline.)
