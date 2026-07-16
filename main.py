"""
main.py — Hive pipeline orchestration script.

Ties the pipeline modules into a single runnable entry point:
1. connector.list_documents()   — ingest (markdown folder or Notion)
2. hash_diff.filter_changed()   — skip unchanged content
3. embeddings.embed_docs()      — vectorize new/changed docs (stored vectors reused)
4. clustering.cluster_docs()    — group ALL docs into topics
5. compiler.compile_docs()      — merge each changed cluster into a wiki page
6. hash_diff.mark_synced()      — record hashes so next run skips them

Usage:
    python main.py                          # cluster mode: one page per topic
    python main.py --provider claude        # use Claude Haiku for synthesis
    python main.py --embed-provider ollama  # local nomic-embed-text embeddings
    python main.py --cluster-threshold 0.75 # stricter topic grouping
    python main.py --topic deployment       # legacy: all changed docs, one page
    python main.py --reset                  # treat all docs as new

Done signals:
    - First run embeds all docs and compiles one wiki page per topic cluster.
    - Second run (no changes) prints "Nothing changed, skipping." with zero
      embedding or LLM calls.
    - Editing one file in sample_docs/ re-embeds only that doc and recompiles
      only its cluster.
"""

from __future__ import annotations

import argparse
import sys

from connectors import markdown_fs, notion
from core.hash_diff import filter_changed, load_embeddings, mark_synced, reset_state, save_embeddings
from core.compiler import compile_docs
from core.clustering import cluster_docs
from core.embeddings import embed_docs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hive knowledge compiler — ingest, diff, and compile markdown docs into a wiki page."
    )
    parser.add_argument(
        "--provider", "-p",
        choices=["ollama", "claude", "nvidia"],
        default="nvidia",
        help="LLM provider for synthesis (default: nvidia, needs NVIDIA_NIM_API_KEY set). Use 'claude' with ANTHROPIC_API_KEY set, or 'ollama' for local/free.",
    )
    parser.add_argument(
        "--topic", "-t",
        default=None,
        help="Force all changed docs into one wiki page under this slug (legacy "
             "single-batch mode). Omit to cluster docs into topics automatically.",
    )
    parser.add_argument(
        "--embed-provider",
        choices=["nvidia", "ollama"],
        default="nvidia",
        help="Embedding provider for topic clustering (default: nvidia).",
    )
    parser.add_argument(
        "--cluster-threshold",
        type=float,
        default=0.7,
        help="Cosine similarity threshold for grouping docs into one topic "
             "(default: 0.7 — e5-family embeddings score high across the board, "
             "0.6 chains unrelated topics together).",
    )
    parser.add_argument(
        "--reset", "-r",
        action="store_true",
        help="Wipe all tracked state before running — treats every doc as new/changed.",
    )
    parser.add_argument(
        "--folder",
        default="sample_docs",
        help="Folder to scan for .md files (default: 'sample_docs'). Ignored for --source notion.",
    )
    parser.add_argument(
        "--source",
        choices=["markdown", "notion"],
        default="markdown",
        help="Document source (default: markdown). Use 'notion' with NOTION_API_KEY set.",
    )
    args = parser.parse_args()

    # --- Optional reset ---
    if args.reset:
        reset_state()
        print("State reset — all documents will be treated as new/changed.")

    # --- 1. Ingest ---
    if args.source == "notion":
        print("Scanning Notion for shared pages/databases...")
        docs = notion.list_documents()
    else:
        print(f"Scanning {args.folder!r} for markdown files...")
        docs = markdown_fs.list_documents(args.folder)
    print(f"Found {len(docs)} document(s).")

    if not docs:
        print("No documents found — nothing to do.")
        return

    # --- 2. Diff ---
    changed = filter_changed(docs)
    skipped = len(docs) - len(changed)

    if skipped > 0:
        print(f"Skipped {skipped} unchanged document(s).")

    if not changed:
        print("Nothing changed, skipping.")
        return

    print(f"{len(changed)} document(s) changed — compiling...")

    # --- 3. Compile ---
    if args.topic is not None:
        # Legacy single-batch mode: everything changed goes into one page.
        try:
            out_paths = [compile_docs(changed, args.topic, provider=args.provider)]
        except Exception as exc:
            print(f"Compilation failed: {exc}", file=sys.stderr)
            print("(State not saved — documents will retry on next run.)")
            sys.exit(1)
    else:
        # Cluster mode: embed what's new/stale, reuse stored vectors for the
        # rest, group ALL docs by topic, recompile only clusters that contain
        # at least one changed doc.
        stored = load_embeddings(docs)
        need_embed = [d for d in docs if f"{d.source}::{d.id}" not in stored]
        try:
            fresh = embed_docs(need_embed, provider=args.embed_provider)
        except Exception as exc:
            print(f"Embedding failed: {exc}", file=sys.stderr)
            print("(State not saved — documents will retry on next run.)")
            sys.exit(1)
        save_embeddings(need_embed, fresh)
        print(f"Embedded {len(fresh)} doc(s), reused {len(stored)} stored vector(s).")

        clusters = cluster_docs(docs, {**stored, **fresh}, threshold=args.cluster_threshold)
        changed_keys = {f"{d.source}::{d.id}" for d in changed}

        out_paths = []
        for slug, members in clusters:
            if not any(f"{m.source}::{m.id}" in changed_keys for m in members):
                print(f"Topic '{slug}': unchanged, skipping.")
                continue
            try:
                out_paths.append(compile_docs(members, slug, provider=args.provider))
            except Exception as exc:
                print(f"Compilation failed for topic '{slug}': {exc}", file=sys.stderr)
                print("(State not saved — documents will retry on next run.)")
                sys.exit(1)

    # --- 4. Record ---
    mark_synced(changed)

    # --- 5. Report ---
    for out_path in out_paths:
        print(f"Compiled → {out_path}")
    print(f"{len(changed)} changed doc(s), {len(out_paths)} page(s). Provider: {args.provider}")
    print("Done.")


if __name__ == "__main__":
    main()