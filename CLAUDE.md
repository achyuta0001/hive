# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Hive is a source-agnostic knowledge compiler. It ingests documents from multiple
sources (markdown/git first, then Notion, then Confluence), normalizes them into
one canonical schema, uses an LLM to merge/synthesize overlapping or related
documents into clean markdown wiki pages, flags contradictions instead of
silently picking one, and serves the result to AI coding agents so they don't
have to re-discover the same knowledge via expensive token-heavy RAG search
every time.

**Core design principle:** everything above the canonical document layer
(`core/canonical.py`) is source-specific and swappable (connectors). Everything
below it is source-agnostic and must never branch on `doc.source`.

**Cost principle:** only pay for compute (embeddings, LLM calls) on content
that is new or changed since the last sync. `core/hash_diff.py` is the gate
that sits between ingestion and anything expensive — nothing should bypass it.

## Commands

```bash
pip install -r requirements.txt

# Run the full pipeline (default: nvidia provider, sample_docs/, automatic
# embedding-based topic clustering — one wiki page per detected topic)
python main.py

# Use local/free Ollama instead (weaker at conflict-flagging, see note below)
python main.py --provider ollama

# Use Claude Haiku instead (requires ANTHROPIC_API_KEY)
python main.py --provider claude

# Legacy single-batch mode: force all changed docs into one page under this slug
python main.py --topic deployment --folder sample_docs

# Tune clustering (0.7 default — e5 embeddings score high, 0.6 chains topics)
python main.py --cluster-threshold 0.75 --embed-provider ollama

# Ingest from Notion instead of markdown (requires NOTION_API_KEY)
python main.py --source notion --topic notion-stress-test

# Ingest from Confluence Cloud (requires CONFLUENCE_BASE_URL, CONFLUENCE_EMAIL,
# CONFLUENCE_API_TOKEN; connector not yet validated against a live site)
python main.py --source confluence

# Wipe hash-tracking state so every doc is treated as new/changed
python main.py --reset

# Run the serving layer (real-time queries, no CLI re-run needed)
uvicorn server.app:app --reload

# Register the MCP server with Claude Code (stdio, needs NVIDIA_NIM_API_KEY in -e)
claude mcp add hive -e NVIDIA_NIM_API_KEY=... -- python3 mcp_server.py
```

There is no test suite, linter, or build step configured yet. Verify changes
manually via the done signals below.

**Manual verification loop (this is how correctness is checked in this repo):**
1. `python main.py --reset` — first run should embed all docs and compile one
   `wiki/<slug>.md` per detected topic cluster (4 pages from `sample_docs/`).
2. `python main.py` again — should print `Nothing changed, skipping.` and make
   zero embedding or LLM calls.
3. Edit one file in `sample_docs/`, run again — only that doc re-embeds and
   only its cluster recompiles; every other cluster prints
   `Topic '<slug>': unchanged, skipping.`
4. `python main.py --topic test-topic` — legacy single-batch mode still works
   (all changed docs into one page, no clustering, no embeddings).

Default provider is `nvidia` (NVIDIA NIM, needs `NVIDIA_NIM_API_KEY` set) —
validated as the only provider so far that reliably produces the
`## Open Conflicts` and `## Sources` sections the system prompt requires.
`--provider ollama` needs Ollama running locally (or reachable via
`OLLAMA_HOST`, see `ollama_setup.md` for remote-laptop setup) but has been
observed to silently drop source documents and skip conflict-flagging on
`llama3.1:8b` — treat it as a free fallback, not the default quality bar.

## Architecture — the pipeline, in order

```
connectors/{markdown_fs,notion}.py → core/hash_diff.py → core/embeddings.py → core/clustering.py → core/compiler.py
   (ingest → Document)              (filter unchanged)   (vectorize changed)   (group by topic)    (LLM merge → wiki/*.md)
```

1. **`core/canonical.py`** — the `Document` pydantic model
   (`id, source, title, content, metadata, permissions, links, source_url,
   last_modified, content_hash`). This is the contract every connector must
   satisfy. Nothing downstream of this file should ever branch on `source`;
   if it needs to, the schema is missing a field — add the field, don't add
   a special case.

2. **`core/hash_diff.py`** — `filter_changed(docs)` compares a SHA-256
   content hash against what's stored in SQLite (`data/state.db`) and
   returns only new/changed documents, stamping `content_hash` onto each.
   `mark_synced(docs)` records hashes after a successful compile.
   `reset_state()` wipes tracking for testing. This is the single biggest
   cost lever in the pipeline — never let anything downstream see a
   document that hasn't passed through this filter.

3. **`core/embeddings.py`** — `embed_docs(docs, provider)` turns Documents
   into vectors for clustering. Providers mirror the compiler switch:
   `"nvidia"` (default — NIM embeddings endpoint via stdlib `urllib`, model
   `nvidia/nv-embedqa-e5-v5`, same `NVIDIA_NIM_API_KEY`; the model caps
   input at 512 tokens so the request passes `"truncate": "END"` and lets
   the server cut, topic signal being front-loaded) or `"ollama"`
   (`nomic-embed-text`, honors `OLLAMA_HOST`). Cost principle applies here
   too: only new/changed docs get embedded — vectors persist in
   `data/state.db` (`doc_embedding` table, keyed by source+id, stamped with
   the content hash they were computed from so stale vectors are detected
   and re-embedded). `save_embeddings`/`load_embeddings` live in
   `core/hash_diff.py`.

4. **`core/clustering.py`** — `cluster_docs(docs, embeddings, threshold)`
   groups ALL docs (fresh + stored vectors) into topics: pairwise cosine
   similarity, edge at ≥ threshold, connected components = clusters. Pure
   stdlib, no numpy/sklearn. Slug per cluster derives from the dominant doc
   (closest to centroid), slugified title, `-2`/`-3` suffixes on collision.
   Default threshold is **0.7, not 0.6** — e5-family embeddings score high
   across the board (observed 0.44–0.74 on unrelated sample docs), and 0.6
   chains everything into one component. A cluster is only recompiled if it
   contains ≥ 1 changed doc; unchanged clusters skip the LLM entirely.
   Docs missing an embedding are excluded from clustering rather than
   guessed at.

5. **`core/permissions.py`** — the capture-only permissions layer (see
   `docs/superpowers/specs/2026-07-17-permissions-layer-design.md`).
   Permission entries are namespaced opaque strings — bare `"local"` or
   `"<namespace>:<type>:<value>"` (e.g. `notion:integration:workspace`,
   future `confluence:group:engineering`); downstream code compares by
   string equality only, never parses. `validate_permissions(doc)` runs in
   `main.py` on every ingested doc before hash-diff, so a connector that
   forgets to populate `permissions` fails loudly. After each successful
   compile, `save_page_permissions(slug, docs)` (in `core/hash_diff.py`,
   `page_permission` table) records the full per-source map
   `{doc_id: [entries]}` for that page — no intersection/union policy is
   baked in. `GET /wiki/{slug}` exposes the map plus a derived
   `restricted` bool as metadata. **Nothing enforces yet** — enforcement
   (caller identity + policy) bolts onto the FastAPI layer when a second
   reader exists, with full per-doc data already recorded. Offline tests:
   `python3 tests/test_permissions.py`.

6. **`connectors/markdown_fs.py`** — the first (and simplest) connector:
   walks a folder recursively for `.md` files, parses YAML frontmatter, and
   returns canonical `Document` objects. `permissions` is `["local"]` — a
   legitimate canonical entry under the capture-only permissions layer,
   not a placeholder.

7. **`connectors/notion.py`** — the second connector, validated against a
   real workspace. `list_documents()` takes no folder arg (Notion has no
   filesystem); it calls `/v1/search` to auto-discover pages/databases
   explicitly shared with the integration token (`NOTION_API_KEY`), then
   filters to only items whose `parent.type == "workspace"` — Notion's
   search API returns every nested page too, not just roots, so treating
   all results as roots causes massive duplication (hit this, fixed it).
   From each root it recursively walks `child_database` rows and nested
   `child_page` blocks, converting common block types (paragraph, headings,
   quote, lists, code, divider) to plain/markdown-ish text. Container pages
   with no content of their own (only nested child pages) are skipped
   rather than emitted as empty Documents. `id` is a path-style string built
   from the title chain (e.g. `"Documents /July/Discipline"`), mirroring
   how `markdown_fs.py` uses relative file paths. Auth is a manually-created
   internal integration token, not OAuth — deliberate: OAuth needs a
   registered public integration and a local callback server, infra not
   justified for a single-user MVP (see "cost principle" above; revisit if
   Hive ever needs multi-user/multi-workspace). `permissions` is
   `["notion:integration:workspace"]` — Notion's API exposes no per-page
   ACLs to internal integrations, so this records the honest scope
   ("whatever the token can see"); real per-page ACLs need OAuth +
   enterprise API, deferred with the rest of the OAuth work.

8. **`connectors/confluence.py`** — the third connector (Confluence
   **Cloud** only). **NOT yet validated against a live site** — built
   against Atlassian API docs with offline fixture tests
   (`python3 tests/test_confluence.py`); treat the first real-site run
   as part of verification (the Notion duplication bug only surfaced
   live). Basic auth via `CONFLUENCE_BASE_URL` / `CONFLUENCE_EMAIL` /
   `CONFLUENCE_API_TOKEN`, stdlib `urllib`, all HTTP through one
   `_get()` seam tests monkeypatch. v2 API for spaces/pages (cursor
   pagination); v1 only for read restrictions (v2 has no equivalent).
   Storage-format XHTML converts to markdown-ish text via an
   `html.parser` subclass — code macros keep their language, unknown
   macros keep inner text, empty container pages are skipped. First
   connector capturing real ACLs: read restrictions →
   `confluence:user:<accountId>` / `confluence:group:<name>`;
   unrestricted pages inherit space permissions and record the honest
   scope `confluence:space:<spaceKey>`. Restriction-fetch failures
   propagate rather than falling back to a broader-looking scope. Ids
   are path-style title chains (`"Space/Parent/Title"`), mirroring the
   other connectors.

9. **`core/compiler.py`** — the only stage that genuinely needs an LLM.
   `compile_docs(docs, topic_slug, provider)` takes a batch of related
   Documents and produces one merged wiki page at `wiki/{topic_slug}.md`.
   Provider is swappable: `"nvidia"` (default — NVIDIA NIM via
   `urllib`/stdlib, e.g. `nemotron-3-super-120b-a12b`, needs
   `NVIDIA_NIM_API_KEY`), `"ollama"` (free, local — models `llama3.1:8b` /
   `nomic-embed-text`, but weak at following the merge/conflict
   instructions), or `"claude"` (`anthropic` SDK, Claude Haiku, paid).
   `SYSTEM_PROMPT` requires exact, verbatim structure: every source gets a
   `## <Title>` section immediately followed by `*Source: \`<id>\`*`, plus
   exactly one `## Open Conflicts` section (must say "None found." if
   empty, never omitted) and exactly one `## Sources` section listing every
   input id. `_validate_output(docs, merged)` checks all of this after the
   LLM call and raises `ValueError` (no retry) if anything's missing or a
   source doc got silently dropped — this happened on a weak local model
   before validation existed. Batches arrive pre-grouped by
   `core/clustering.py` (or as one manual batch in `--topic` legacy mode).
   Before the LLM call, `core/precheck.py`'s deterministic pre-checks
   (`find_candidate_conflicts` — numeric-value diff with context anchor,
   timestamp staleness ≥180 days with vocabulary overlap, frontmatter
   mismatch on non-authorial keys) run over the batch; any candidates are
   appended to the user prompt via `format_hints` as hints the model must
   explicitly confirm or dismiss in `## Open Conflicts`. Hints never
   resolve or suppress anything, and a clean batch leaves the prompt
   byte-identical. Offline tests: `python3 tests/test_precheck.py`
   (no network, no DB).

10. **`main.py`** — orchestrates the pipeline and prints what happened
   (embedded vs. reused vectors, compiled vs. skipped clusters) so the
   hash-diff behavior stays observable. `--source markdown|notion` selects
   the connector; `--embed-provider nvidia|ollama` the embedding backend;
   `--cluster-threshold` tunes grouping; `--topic <slug>` forces legacy
   single-batch mode (no clustering, no embeddings).

11. **`server/app.py`** — the serving layer: a thin, long-lived FastAPI
   process wrapping `core/` functions directly, no new business logic.
   `GET /wiki` lists compiled topics, `GET /wiki/{topic_slug}` fetches one.
   `POST /check-conflicts` reuses `compile_docs` itself — it builds a
   synthetic 2-doc batch (the existing compiled page as baseline + new
   candidate content) against a scratch topic slug (`_conflict_check_*`,
   deleted after reading), so real-time conflict checks never mutate the
   actual wiki page. This exists so callers don't pay a cold-process +
   full-rescan cost every time they want an answer — see the plan at
   `.claude/plans/frolicking-drifting-milner.md` for the full rationale
   (API scope, why not full-text search yet, agent-integration design).

12. **`mcp_server.py`** — an MCP server (stdio transport) for Claude Code,
   exposing `hive_get_wiki_page`, `hive_list_topics`, `hive_check_conflicts`
   as MCP tools. Deliberately a thin adapter that imports and calls
   `server/app.py`'s functions directly (same process, no HTTP hop) — there
   is exactly one implementation of each operation behind both the HTTP API
   and MCP, so they can't drift out of sync. Copilot integration is
   intentionally *not* built here: compiled `wiki/*.md` files are already
   plain markdown Copilot picks up as workspace context with zero new code,
   and Copilot has no MCP-equivalent tool-calling surface today.

## Things not to compromise on

- **Never let the compiler silently resolve a contradiction it wasn't sure
  about.** The `## Open Conflicts` section in `compiler.py`'s system prompt
  is the entire safety mechanism of this project. Weakening this
  instruction to make output "look cleaner" is a regression.
- **Never call an LLM on content `hash_diff` already marked unchanged.**
- **Never let a connector leak source-specific logic below the canonical
  layer.** If `compiler.py` or any future permission/linting code branches
  on `doc.source`, the canonical schema is incomplete — fix the schema.
- Permissions are **capture-only**: connectors must populate
  `Document.permissions` with valid namespaced entries (`main.py` fails
  loudly if they don't), and every compiled page's per-source map is
  recorded in `state.db`. Nothing enforces yet — do not add caller
  identity/filtering infra before a second reader exists, and do not let
  a new connector ship with empty or made-up permission entries.
- **Don't remove or weaken `_validate_output`'s checks** in `compiler.py` —
  it's the safety net that catches a model silently dropping a source doc
  or omitting a required section, which has actually happened.

## Planned next steps (not yet built, for context on direction)

- `pgvector`/Postgres once SQLite's naive hash tracking becomes limiting
  (explicitly not before — don't add infra ahead of the need).
- Live validation of the Confluence connector against a real site
  (free-tier Confluence Cloud works) — the connector ships offline-tested
  only.
- SQLite FTS5 or simple vector search on top of the serving layer, once
  there's enough compiled content that slug-keyed lookups aren't sufficient
  (explicitly not before — the current `server/app.py` is slug-lookup only,
  deliberately no search yet).
- OAuth for connectors, if/when Hive needs multi-user or multi-workspace
  support — explicitly deferred for now (see `connectors/notion.py` note
  above).
- Licensing/billing infra, only once there's a real self-host customer
  conversation — see the monetization section of
  `.claude/plans/frolicking-drifting-milner.md` for the reasoning
  (self-host + license first, hosted SaaS later, not the reverse).
