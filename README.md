# Hive — Knowledge Compiler

**Purpose of this file:** hand this to any AI model or collaborator so they
have full context on what this project is, what's already built, and what's
deliberately deferred — without needing the full chat history.
(`CLAUDE.md` is the deeper per-module reference; this is the overview.)

---

## What this project is

A source-agnostic knowledge compiler. It ingests documents from multiple
sources (markdown folders, Notion, Confluence), normalizes them into one
canonical schema, clusters them into topics via embeddings, uses an LLM to
merge/synthesize each topic's overlapping documents into a clean markdown
wiki page, flags contradictions instead of silently picking one, and serves
the result to AI coding agents (Claude Code via MCP, Copilot via plain
markdown) so they don't have to re-discover the same knowledge via
expensive token-heavy RAG search every time.

**Core design principle:** everything above the canonical document layer
(`core/canonical.py`) is source-specific and swappable (connectors).
Everything below it is source-agnostic and never branches on `doc.source`.

**Cost principle:** only pay for compute (embeddings, LLM calls) on content
that is new or changed since the last sync. `core/hash_diff.py` is the gate
in front of everything expensive — and it records what it saved
(`GET /stats`: docs skipped, estimated tokens not reprocessed, measured at
the gate).

---

## Current state (2026-07): pipeline complete, all core features shipped

```text
connectors/{markdown_fs,notion,confluence}.py   ingest → canonical Document
        ↓
core/permissions.py                             validate ACL capture (loud failure)
        ↓
core/hash_diff.py                               drop unchanged content (SQLite state)
        ↓
core/embeddings.py                              vectorize changed docs (NVIDIA NIM / Ollama)
        ↓
core/clustering.py                              cosine threshold → connected components → topics
        ↓
core/precheck.py + core/compiler.py             deterministic conflict hints → LLM merge
        ↓
wiki/<topic>.md                                 one page per topic, with ## Open Conflicts
        ↓
server/app.py (FastAPI) + mcp_server.py (MCP)   real-time serving, one implementation
```

- **Three connectors:** markdown filesystem, Notion (validated against a
  real workspace), Confluence Cloud (**offline-tested only** — not yet run
  against a live site; first real-site run is part of verification).
- **Permissions (capture-only):** namespaced entries
  (`local`, `notion:integration:workspace`, `confluence:group:<name>`, …)
  validated at ingest; per-page permission maps recorded in SQLite and
  exposed as metadata. Nothing enforces yet — one user; enforcement bolts
  onto the serving layer when a second reader exists.
- **Conflict safety:** the compiler's system prompt requires an
  `## Open Conflicts` section (never omitted); `_validate_output` rejects
  output that drops a source or a required section; `core/precheck.py`
  feeds deterministic candidate conflicts (numeric diffs, timestamp
  staleness, frontmatter mismatches) as hints the model must confirm or
  dismiss — never auto-resolved.
- **Serving:** `GET /wiki`, `GET /wiki/{slug}` (content + permissions),
  `GET /stats`, `POST /check-conflicts` (reuses the compiler against a
  scratch slug — never mutates the real page). MCP tools
  (`hive_get_wiki_page`, `hive_list_topics`, `hive_check_conflicts`,
  `hive_get_stats`) call the same functions directly.
- **CI:** eight offline test suites (`tests/`) run on every push/PR —
  no network, no keys. Coverage: pre-checks, permissions, Confluence
  fixtures, Notion fixtures, clustering, hash-diff gate, serving
  endpoints, savings stats.

## Tech stack

- **Python 3.11+**, `pydantic` for the canonical schema,
  `python-frontmatter` for markdown, stdlib `sqlite3` for all state
  (hashes, embeddings, page permissions, savings stats), stdlib `urllib`
  for every HTTP call — no requests/numpy/sklearn.
- **LLM synthesis:** NVIDIA NIM default (`nemotron-3-super-120b-a12b`,
  `NVIDIA_NIM_API_KEY`) — the only provider validated to reliably produce
  the required conflict/source sections. Fallbacks: `--provider claude`
  (Anthropic SDK, Haiku) or `--provider ollama` (free/local, weak at
  instruction-following — validation catches its failures).
- **Embeddings:** NVIDIA NIM default (`nv-embedqa-e5-v5`) or
  `--embed-provider ollama` (`nomic-embed-text`). e5 similarity scores run
  high, hence cluster threshold 0.7 (0.6 chains unrelated topics).
- **Serving:** `fastapi`/`uvicorn`; `mcp` SDK for the Claude Code server.

## Quickstart

```bash
pip install -r requirements.txt
export NVIDIA_NIM_API_KEY=...

python main.py --reset        # full pipeline: embed, cluster, compile wiki/
python main.py                # → "Nothing changed, skipping." (zero API calls)
python tests/test_precheck.py # offline suites, no keys needed

uvicorn server.app:app --reload                          # HTTP serving
claude mcp add hive -e NVIDIA_NIM_API_KEY=... -- python3 mcp_server.py
```

`CLAUDE.md` documents every module, the manual verification loop, and the
full command matrix (`--source notion|confluence`, `--topic` legacy mode,
`--cluster-threshold`, …).

---

## Things not to compromise on, regardless of who continues this

- **Never let the compiler silently resolve a contradiction it wasn't sure
  about.** `## Open Conflicts` is the entire safety mechanism. Removing or
  weakening it "to make output cleaner" is a regression.
- **Never call an LLM (or embed) content the hash-diff already marked
  unchanged.** This is the cost control for the whole pipeline.
- **Never let a connector leak source-specific logic below the canonical
  layer.** If anything downstream branches on `doc.source`, the schema is
  missing a field — add the field, not a special case.
- **Don't weaken `_validate_output`** — it has caught real models silently
  dropping source documents.
- **Permissions are capture-only, and honestly so.** Connectors must
  record real (or honestly-scoped) ACL entries, never fake `local`; don't
  build enforcement infra before a second reader exists.

## Open items

- **Confluence live validation** — connector is fixture-tested only; needs
  a real site (free-tier Confluence Cloud works). The Notion connector's
  worst bug only surfaced against a live workspace.
- **Ollama paths untested live** (embeddings + synthesis) — needs the
  Ollama host machine online.

## Deferred by design (don't build ahead of the need)

- Postgres/`pgvector` (SQLite is fine at current scale)
- Full-text/vector search on the serving layer (slug lookup suffices)
- OAuth for connectors (single-user; internal tokens work)
- Enforcement layer for permissions (one reader)
- Licensing/billing (no self-host customer conversation yet) — see
  `.claude/plans/frolicking-drifting-milner.md` for the monetization
  reasoning (self-host + license first, hosted SaaS later)

---

## Context this doesn't need to know

This project originated as a way to reduce token-heavy RAG search against
Confluence at a bank, but this standalone version is built independently on
personal hardware/data to avoid any IP overlap with employer work.
