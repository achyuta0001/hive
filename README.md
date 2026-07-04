# Hive — Knowledge Compiler (Project README)

**Purpose of this file:** hand this to any AI model or collaborator so they have full context on what this project is, what's already built, and what to build next — without needing the full chat history.

---

## What this project is

A source-agnostic knowledge compiler. It ingests documents from multiple
sources (markdown/git first, then Notion, then Confluence), normalizes them
into one canonical schema, uses an LLM to merge/synthesize overlapping or
related documents into clean markdown wiki pages, flags contradictions
instead of silently picking one, and serves the result to AI coding
agents (Claude Code, Copilot, etc.) so they don't have to re-discover the
same knowledge via expensive token-heavy RAG search every time.

**Core design principle:** everything above the canonical document layer
is source-specific and swappable (connectors). Everything below it is
source-agnostic and should never change when a new connector is added.

**Cost principle:** only pay for compute (embeddings, LLM calls) on
content that is new or changed since the last sync. A hash-diff gate
sits right after ingestion and before anything expensive.

---

## Tech stack

- **Language:** Python 3.11+ (chosen because the embeddings/RAG/LLM
  tooling ecosystem is Python-first; a Go or Java rewrite is a
  post-validation decision, not a day-one one)
- **Schema validation:** `pydantic`
- **Markdown parsing:** `python-frontmatter`
- **State/hash tracking:** `sqlite3` (stdlib) — will grow into Postgres +
  `pgvector` once embeddings/clustering are added
- **Local LLM/embeddings (dev, free):** `ollama` (models: `llama3.1:8b`,
  `nomic-embed-text`)
- **Production-quality LLM (synthesis only, paid):** `anthropic` SDK,
  Claude Haiku, called only on hash-diffed new/changed content
- **Target dev machine:** MSI GF75 Thin, 16GB RAM — everything in the
  MVP stage runs on this with zero cloud cost

---

## Folder structure

```text
hive/
├── connectors/
│   └── markdown_fs.py       # DONE — first connector, no auth needed
├── core/
│   ├── canonical.py         # DONE — the Document schema every connector must produce
│   ├── hash_diff.py         # DONE — skips unchanged content, the #1 cost lever
│   └── compiler.py          # DONE — the one stage that genuinely needs an LLM
├── wiki/                    # output — compiled markdown lands here (auto-created)
├── data/
│   └── state.db             # sqlite — tracks content hashes (auto-created)
├── sample_docs/             # TODO — put 5-6 fake overlapping/contradicting .md files here
├── requirements.txt         # TODO
└── main.py                  # TODO — ties everything together, run manually for now
```

---

## What's already built (as of this file)

1. **`core/canonical.py`** — the `Document` pydantic model. Fields:
   `id, source, title, content, metadata, permissions, links,
   source_url, last_modified, content_hash`. This is the contract every
   connector must satisfy. Nothing downstream should ever branch on
   `source` — if it does, that's a bug to fix.

2. **`core/hash_diff.py`** — `filter_changed(docs)` returns only new/changed
   documents by comparing a SHA-256 content hash against what's stored in
   SQLite (`data/state.db`). `mark_synced(docs)` records the new hashes
   after a successful compile. `reset_state()` wipes tracking for testing.

3. **`connectors/markdown_fs.py`** — `list_documents(folder)` walks a
   folder recursively for `.md` files, parses YAML frontmatter, and
   returns a list of canonical `Document` objects. `fetch(folder, doc_id)`
   gets one by id.

4. **`core/compiler.py`** — `compile_docs(docs, topic_slug, provider)`
   takes a batch of related Documents and produces ONE merged wiki page,
   written to `wiki/{topic_slug}.md`. Provider is swappable:
   `"ollama"` (default, free, local — good enough to prove the pipeline)
   or `"claude"` (better quality, use once judging real synthesis
   quality against real pilot data matters). The system prompt
   explicitly instructs the model to flag contradictions in an
   `## Open Conflicts` section rather than silently resolving them —
   this is the actual point of the whole project, so don't weaken this
   instruction to make outputs "look cleaner."

---

## What to build next, in order

### Step A — `sample_docs/` (do this first, it's just content)
Write 5-6 fake `.md` files that deliberately overlap and contradict each
other in small ways (e.g. two docs both describing a deployment process,
one saying "run migrations before deploy" and another saying "after").
This is the test fixture for everything else. Include YAML frontmatter
with at least a `title:` field in a couple of them to test that path.

### Step B — `requirements.txt`
```text
pydantic>=2
python-frontmatter
ollama
anthropic
```

### Step C — `main.py`
Wire the three finished modules together into one runnable script:
1. `markdown_fs.list_documents("sample_docs")` → get all docs
2. `hash_diff.filter_changed(docs)` → get only new/changed ones
3. If any changed docs exist, group them (for now: naively treat all
   changed docs as one batch/topic — smarter grouping via embeddings
   comes later) and call `compiler.compile_docs(changed, "test-topic")`
4. `hash_diff.mark_synced(changed)` after a successful compile
5. Print what happened (compiled vs. skipped) so the loop is visible

**Done signal for this step:** run `main.py` twice in a row. First run
compiles something. Second run says "nothing changed, skipping" and makes
zero LLM calls.

**Done signal for the whole MVP:** edit one file in `sample_docs/`, run
`main.py` again — only that content triggers a recompile, not everything.

### Step D — once the loop above works end to end
Only after Step C is proven:
- Add local embeddings (`nomic-embed-text` via Ollama) + a simple
  cosine-similarity grouping function, so documents get clustered by
  topic automatically instead of naively batched.
- Add `pgvector`/Postgres once SQLite's naive approach becomes limiting
  (not before — don't add infra ahead of the need).
- Add rule-based conflict pre-checks (timestamp diff, numeric value diff,
  frontmatter mismatch) so the LLM only gets called on genuinely
  ambiguous contradictions, not ones a simple rule already caught.
- Add the Notion connector (second source — clean API, native webhooks,
  reuses everything below the canonical layer untouched).
- Add the Confluence connector last (messiest API surface: v1/v2 split,
  storage-format XML).
- Add a serving layer (FastAPI + SQLite FTS5 or simple vector search)
  once there's an actual wiki worth querying.

---

## Things not to compromise on, regardless of who continues this

- **Never let the compiler silently resolve a contradiction it wasn't
  sure about.** The `## Open Conflicts` section in the system prompt is
  the entire safety mechanism of this project. If a future iteration
  removes it "to make output cleaner," that's a regression, not an
  improvement.
- **Never call an LLM on content the hash-diff already marked
  unchanged.** This is the cost control for the whole pipeline.
- **Never let a connector leak source-specific logic below the canonical
  layer.** If `compiler.py` or any future linter/permission code ever
  branches on `doc.source`, that's a sign the canonical schema is
  incomplete and needs a new field, not a special case.
- **Permissions are not implemented yet** (`markdown_fs.py` currently
  hardcodes `permissions=["local"]`). Before adding any source that has
  real access control (Notion, Confluence), a proper permission-mapping
  layer needs to exist first — do not skip this to move faster.

---

## Context this doesn't need to know
This project originated as a way to reduce token-heavy RAG search against
Confluence at a bank, but the standalone version described here is being
built independently on personal hardware/data (sample markdown files
only) to avoid any IP overlap with employer work.
