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

# Run the full pipeline (default: nvidia provider, "test-topic" slug, sample_docs/)
python main.py

# Use local/free Ollama instead (weaker at conflict-flagging, see note below)
python main.py --provider ollama

# Use Claude Haiku instead (requires ANTHROPIC_API_KEY)
python main.py --provider claude

# Custom topic slug / input folder
python main.py --topic deployment --folder sample_docs

# Ingest from Notion instead of markdown (requires NOTION_API_KEY)
python main.py --source notion --topic notion-stress-test

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
1. `python main.py` — first run should compile `wiki/test-topic.md`.
2. `python main.py` again — should print `Nothing changed, skipping.` and make
   zero LLM calls.
3. Edit one file in `sample_docs/`, run again — only that changed content
   should trigger recompilation, not the whole batch.

Default provider is `nvidia` (NVIDIA NIM, needs `NVIDIA_NIM_API_KEY` set) —
validated as the only provider so far that reliably produces the
`## Open Conflicts` and `## Sources` sections the system prompt requires.
`--provider ollama` needs Ollama running locally (or reachable via
`OLLAMA_HOST`, see `ollama_setup.md` for remote-laptop setup) but has been
observed to silently drop source documents and skip conflict-flagging on
`llama3.1:8b` — treat it as a free fallback, not the default quality bar.

## Architecture — the pipeline, in order

```
connectors/{markdown_fs,notion}.py  →  core/hash_diff.py  →  core/compiler.py
   (ingest → Document)                  (filter unchanged)      (LLM merge → wiki/*.md)
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

3. **`connectors/markdown_fs.py`** — the first (and simplest) connector:
   walks a folder recursively for `.md` files, parses YAML frontmatter, and
   returns canonical `Document` objects. `permissions` is currently
   hardcoded to `["local"]` — a real permission-mapping layer must exist
   before adding any connector with real access control (Notion,
   Confluence).

4. **`connectors/notion.py`** — the second connector, validated against a
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
   Hive ever needs multi-user/multi-workspace).

5. **`core/compiler.py`** — the only stage that genuinely needs an LLM.
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
   before validation existed. Grouping documents into topics is currently
   naive (all changed docs treated as one batch) — smarter clustering via
   embeddings is a planned follow-up, not yet implemented.

6. **`main.py`** — orchestrates the four steps above and prints what
   happened (compiled vs. skipped) so the hash-diff behavior stays
   observable. `--source markdown|notion` selects the connector.

7. **`server/app.py`** — the serving layer: a thin, long-lived FastAPI
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

8. **`mcp_server.py`** — an MCP server (stdio transport) for Claude Code,
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
- Permissions are not implemented beyond the `["local"]` placeholder —
  don't wire up a source with real ACLs (Notion, Confluence) before that
  layer exists.
- **Don't remove or weaken `_validate_output`'s checks** in `compiler.py` —
  it's the safety net that catches a model silently dropping a source doc
  or omitting a required section, which has actually happened.

## Planned next steps (not yet built, for context on direction)

- Local embeddings (`nomic-embed-text` via Ollama) + cosine-similarity
  grouping so documents cluster by topic automatically instead of being
  naively batched.
- `pgvector`/Postgres once SQLite's naive hash tracking becomes limiting
  (explicitly not before — don't add infra ahead of the need).
- Rule-based conflict pre-checks (timestamp diff, numeric value diff,
  frontmatter mismatch) so the LLM is only called on genuinely ambiguous
  contradictions.
- Confluence connector next (messiest API surface of the three: v1/v2
  split, storage-format XML).
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
