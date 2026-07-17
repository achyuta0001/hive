"""
Offline tests for sync-stats recording (cost-gate savings metric).

Run: python -m pytest tests/test_stats.py  (or python tests/test_stats.py)
"""

from __future__ import annotations
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.hash_diff as hash_diff
from core.hash_diff import load_sync_stats, record_sync_stats, reset_state


def _with_temp_db(fn):
    original = hash_diff.DB_PATH
    with tempfile.TemporaryDirectory() as tmp:
        hash_diff.DB_PATH = Path(tmp) / "state.db"
        try:
            fn()
        finally:
            hash_diff.DB_PATH = original


def test_empty_stats():
    def check():
        assert load_sync_stats() == {
            "runs": 0, "docs_skipped_total": 0, "tokens_saved_estimate_total": 0,
        }
    _with_temp_db(check)


def test_record_and_accumulate():
    def check():
        record_sync_stats(6, 0, 0)          # first run, everything new
        record_sync_stats(6, 6, 2400)       # nothing changed
        record_sync_stats(6, 5, 2000)       # one doc edited
        stats = load_sync_stats()
        assert stats["runs"] == 3
        assert stats["docs_skipped_total"] == 11
        assert stats["tokens_saved_estimate_total"] == 4400
    _with_temp_db(check)


def test_reset_clears_stats():
    def check():
        record_sync_stats(3, 3, 900)
        reset_state()
        assert load_sync_stats()["runs"] == 0
    _with_temp_db(check)


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    sys.exit(1 if failures else 0)
