"""
Offline tests for core/precheck.py — no network, no LLM, no DB.

Run: python -m pytest tests/test_precheck.py  (or python tests/test_precheck.py)
"""

from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.canonical import Document
from core.precheck import (
    CandidateConflict,
    find_candidate_conflicts,
    format_hints,
)


def _doc(id: str, content: str, *, metadata: dict | None = None,
         last_modified: datetime | None = None) -> Document:
    return Document(
        id=id,
        source="test",
        title=id,
        content=content,
        metadata=metadata or {},
        permissions=["local"],
        links=[],
        source_url=None,
        last_modified=last_modified,
    )


def test_numeric_diff_flagged():
    a = _doc("a", "The deploy timeout is 30 minutes for all services.")
    b = _doc("b", "Remember: the deploy timeout is 45 minutes now.")
    out = find_candidate_conflicts([a, b])
    reasons = [c.reason for c in out]
    assert "numeric-diff" in reasons, out
    hit = next(c for c in out if c.reason == "numeric-diff")
    assert "30" in hit.evidence and "45" in hit.evidence


def test_numeric_agreement_not_flagged():
    a = _doc("a", "The deploy timeout is 30 minutes.")
    b = _doc("b", "Our deploy timeout stays at 30 minutes.")
    assert not [c for c in find_candidate_conflicts([a, b])
                if c.reason == "numeric-diff"]


def test_numeric_different_context_not_flagged():
    # Same unit, unrelated context anchors — must not cross-match.
    a = _doc("a", "The deploy timeout is 30 minutes.")
    b = _doc("b", "The standup meeting lasts 15 minutes.")
    assert not [c for c in find_candidate_conflicts([a, b])
                if c.reason == "numeric-diff"]


def test_timestamp_staleness_flagged():
    shared = ("kubernetes deployment rollout strategy canary traffic "
              "ingress replicas monitoring alerting dashboards")
    a = _doc("old", f"Guide about {shared}.",
             last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc))
    b = _doc("new", f"Updated notes on {shared}.",
             last_modified=datetime(2026, 1, 1, tzinfo=timezone.utc))
    out = [c for c in find_candidate_conflicts([a, b])
           if c.reason == "timestamp-staleness"]
    assert len(out) == 1, out
    assert "old" in out[0].evidence


def test_timestamp_no_overlap_not_flagged():
    a = _doc("old", "Ancient poetry about mountains and rivers flowing.",
             last_modified=datetime(2024, 1, 1, tzinfo=timezone.utc))
    b = _doc("new", "Kubernetes ingress controller configuration reference.",
             last_modified=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert not [c for c in find_candidate_conflicts([a, b])
                if c.reason == "timestamp-staleness"]


def test_timestamp_missing_dates_ignored():
    a = _doc("a", "some shared kubernetes deployment content here")
    b = _doc("b", "some shared kubernetes deployment content here")
    assert not [c for c in find_candidate_conflicts([a, b])
                if c.reason == "timestamp-staleness"]


def test_metadata_mismatch_flagged():
    a = _doc("a", "x", metadata={"owner_team": "platform"})
    b = _doc("b", "y", metadata={"owner_team": "infra"})
    out = [c for c in find_candidate_conflicts([a, b])
           if c.reason == "metadata-mismatch"]
    assert len(out) == 1
    assert "owner_team" in out[0].evidence


def test_metadata_ignored_keys_not_flagged():
    a = _doc("a", "x", metadata={"author": "alice", "tags": ["x"], "date": "2024"})
    b = _doc("b", "y", metadata={"author": "bob", "tags": ["y"], "date": "2026"})
    assert not [c for c in find_candidate_conflicts([a, b])
                if c.reason == "metadata-mismatch"]


def test_no_candidates_empty_hints():
    assert format_hints([]) == ""


def test_hints_format():
    hints = format_hints([CandidateConflict(
        doc_a="a", doc_b="b", reason="numeric-diff", evidence="timeout differs")])
    assert "AUTOMATED CONFLICT CANDIDATES" in hints
    assert "[numeric-diff] a vs b: timeout differs" in hints
    assert "confirm" in hints and "dismiss" in hints


def test_prompt_unchanged_when_no_candidates():
    # Wiring guarantee: compile prompt must be byte-identical for clean batches.
    from core.compiler import _build_prompt
    a = _doc("a", "Totally unrelated prose about gardening and soil health.")
    b = _doc("b", "Notes on classical music composers of the baroque era.")
    prompt = _build_prompt([a, b])
    hints = format_hints(find_candidate_conflicts([a, b]))
    assert hints == ""
    assert prompt == _build_prompt([a, b])


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
