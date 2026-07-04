"""
main.py — Hive pipeline orchestration script.

Ties together the three finished modules into a single runnable entry point:
1. markdown_fs.list_documents()  — ingest all .md files from sample_docs/
2. hash_diff.filter_changed()    — skip unchanged content
3. compiler.compile_docs()       — merge changed docs into a wiki page
4. hash_diff.mark_synced()       — record hashes so next run skips them

Usage:
    python main.py                          # default: ollama, topic="test-topic"
    python main.py --provider claude        # use Claude Haiku instead of Ollama
    python main.py --topic deployment       # custom topic slug
    python main.py --reset                  # treat all docs as new

Done signals:
    - First run compiles a wiki page.
    - Second run (no changes) prints "Nothing changed, skipping." with zero LLM calls.
    - Editing one file in sample_docs/ triggers recompilation of only that content.
"""

from __future__ import annotations

import argparse
import sys

from connectors.markdown_fs import list_documents
from core.hash_diff import filter_changed, mark_synced, reset_state
from core.compiler import compile_docs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hive knowledge compiler — ingest, diff, and compile markdown docs into a wiki page."
    )
    parser.add_argument(
        "--provider", "-p",
        choices=["ollama", "claude"],
        default="ollama",
        help="LLM provider for synthesis (default: ollama). Use 'claude' with ANTHROPIC_API_KEY set.",
    )
    parser.add_argument(
        "--topic", "-t",
        default="test-topic",
        help="Topic slug for the output wiki page (default: 'test-topic').",
    )
    parser.add_argument(
        "--reset", "-r",
        action="store_true",
        help="Wipe all tracked state before running — treats every doc as new/changed.",
    )
    parser.add_argument(
        "--folder",
        default="sample_docs",
        help="Folder to scan for .md files (default: 'sample_docs').",
    )
    args = parser.parse_args()

    # --- Optional reset ---
    if args.reset:
        reset_state()
        print("State reset — all documents will be treated as new/changed.")

    # --- 1. Ingest ---
    print(f"Scanning {args.folder!r} for markdown files...")
    docs = list_documents(args.folder)
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
    try:
        out_path = compile_docs(changed, args.topic, provider=args.provider)
    except Exception as exc:
        print(f"Compilation failed: {exc}", file=sys.stderr)
        print("(State not saved — documents will retry on next run.)")
        sys.exit(1)

    # --- 4. Record ---
    mark_synced(changed)

    # --- 5. Report ---
    print(f"Compiled {len(changed)} changed doc(s) → {out_path}")
    print(f"Provider: {args.provider}")
    print("Done.")


if __name__ == "__main__":
    main()