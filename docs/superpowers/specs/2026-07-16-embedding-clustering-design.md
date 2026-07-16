# Embedding-Based Topic Clustering — Design

Date: 2026-07-16 · Status: approved

## Goal

Replace the naive "all changed docs = one batch = one wiki page" compile with
automatic topic clustering via embeddings, so a sync produces one wiki page
per real topic. Preserve the hash-diff cost principle exactly: never embed or
LLM-compile content that hasn't changed.

## Decisions (user-approved)

- **Embedding providers: both** — `"nvidia"` (NIM embeddings endpoint, stdlib
  urllib, same `NVIDIA_NIM_API_KEY`) default, `"ollama"` (`nomic-embed-text`)
  fallback. New CLI flag `--embed-provider`.
- **Clustering: cosine threshold + connected components, pure Python.** No
  new dependencies. Docs with similarity ≥ threshold link; connected
  components are clusters. `--cluster-threshold`, default 0.6.
- **Topic naming: derive from dominant doc title.** Dominant = doc closest to
  cluster centroid; slugify its title. No extra LLM call. Known tradeoff:
  name can flip if the central doc changes.
- **`--topic` becomes an override**: when passed explicitly, old single-batch
  behavior, clustering skipped. Default run clusters automatically.

## New files

### `core/embeddings.py`

- `embed_docs(docs: list[Document], provider: str = "nvidia") -> dict[str, list[float]]`
  keyed by `(doc.source, doc.id)` composite string `f"{source}::{id}"`.
- NVIDIA: POST `https://integrate.api.nvidia.com/v1/embeddings`, stdlib
  `urllib.request`, model `nvidia/nv-embedqa-e5-v5`, key from
  `NVIDIA_NIM_API_KEY` or `NVIDIA_API_KEY`. Truncate input per API limits.
- Ollama: `ollama` python client, model `nomic-embed-text`, honors
  `OLLAMA_HOST`.
- No branching on `doc.source` for logic — provider is a call-site param.

### `core/clustering.py`

- `cluster_docs(docs, embeddings, threshold=0.6) -> list[tuple[str, list[Document]]]`
  returning `(slug, cluster_members)` pairs.
- Cosine similarity in pure Python; union-find or BFS for components.
- Slug: doc nearest cluster centroid → title → lowercase, alphanumeric+dash.
- Singleton clusters allowed (a doc unlike everything else gets its own page).

## Changed files

### `core/hash_diff.py` — vector persistence

- New table `doc_embedding (source, doc_id, content_hash, vector TEXT/*json*/, PRIMARY KEY(source, doc_id))`.
- `save_embeddings(docs, vectors)` — upsert after embedding.
- `load_embeddings(docs) -> dict[key, list[float]]` — returns stored vectors
  only where stored `content_hash` matches the doc's current hash (stale
  vectors ignored, forcing re-embed).
- `reset_state()` also clears `doc_embedding`.

### `main.py` — new flow

```
connector → filter_changed → embed changed docs (only) → save_embeddings →
load_embeddings for unchanged docs → cluster ALL docs →
for each cluster containing ≥1 changed doc: compile_docs(cluster, slug) →
mark_synced(changed)
```

- Unchanged clusters: zero LLM calls, print "skipped".
- If `--topic` given explicitly: bypass clustering, current behavior verbatim.
  Implementation: change argparse default to `None`; `None` means cluster,
  any value means legacy single-batch (so "test-topic" is no longer a silent
  default).
- New flags: `--embed-provider {nvidia,ollama}` (default nvidia),
  `--cluster-threshold FLOAT` (default 0.6).

## Cost rule (invariant)

Only docs surviving `filter_changed` are embedded. Unchanged docs reuse
stored vectors. A cluster recompiles iff it contains ≥1 changed doc. If a
doc's stored vector is missing/stale but the doc is unchanged (e.g. first
run after upgrade), it is embedded once and stored — embedding cost, no LLM
cost.

## Error handling

- Embedding call failure: abort run before any LLM call, state not saved,
  docs retry next run (same pattern as compile failure in main.py).
- Empty/whitespace doc content: skip embedding, exclude from clustering.

## Verification

1. `python main.py --reset` on `sample_docs/` — expect >1 wiki page if docs
   span topics, sensible slugs.
2. Run again — "Nothing changed, skipping.", zero embed + zero LLM calls.
3. Edit one doc — only its cluster recompiles.
4. `python main.py --topic test-topic` — single-page legacy behavior intact.
