"""
Rule-based conflict pre-checks: cheap, deterministic scans that run before
the LLM and surface *candidate* contradictions between documents in a batch.

These never resolve or suppress anything. Their output is appended to the
compile prompt as hints the model must explicitly confirm or dismiss in its
"## Open Conflicts" section - the LLM stays the final judge, and the
"never silently resolve" principle stays intact. The point is only that the
model doesn't have to *notice* a numeric or metadata disagreement on its
own; we point at it.

Source-agnostic by design: operates purely on canonical Document fields,
never branches on doc.source.
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from itertools import combinations

from core.canonical import Document

# last_modified gap (days) beyond which two docs sharing vocabulary are
# flagged as a staleness candidate: the older one may describe a superseded
# state of the same topic.
STALENESS_DAYS = 180

# Minimum shared distinctive words for two docs to count as "about the same
# thing" for the timestamp check (crude overlap guard so we don't flag every
# old doc against every new one).
_MIN_SHARED_TERMS = 8

# number + optional unit word immediately after it ("30 minutes", "3 retries",
# "99.9 %"). Captures the preceding few words as context.
_NUMBER_RE = re.compile(
    r"((?:\S+\s+){0,4})(\d+(?:\.\d+)?)\s*(%|percent|seconds?|secs?|minutes?|"
    r"mins?|hours?|days?|weeks?|retries|attempts|replicas?|instances?|"
    r"gb|mb|tb|ms)\b",
    re.IGNORECASE,
)

_WORD_RE = re.compile(r"[a-z][a-z0-9_-]{4,}")

# Frontmatter/metadata keys that are about the doc itself, not its subject -
# two docs legitimately differ on these, so they are never conflict signals.
_META_KEYS_IGNORED = {"author", "authors", "date", "created", "updated", "tags", "title"}


@dataclass
class CandidateConflict:
    doc_a: str          # Document.id
    doc_b: str          # Document.id
    reason: str         # "numeric-diff" | "timestamp-staleness" | "metadata-mismatch"
    evidence: str       # short human-readable snippet for the LLM prompt


def _distinctive_terms(doc: Document) -> set[str]:
    return set(_WORD_RE.findall(doc.content.lower()))


def _numbers_by_context(doc: Document) -> dict[str, set[str]]:
    """Map "<context keyword> <unit>" -> set of values found in the doc."""
    found: dict[str, set[str]] = {}
    for match in _NUMBER_RE.finditer(doc.content):
        context, value, unit = match.groups()
        unit = unit.lower().rstrip("s")
        # anchor on the most distinctive context word, if any
        words = _WORD_RE.findall(context.lower())
        anchor = words[-1] if words else ""
        key = f"{anchor} {unit}".strip()
        found.setdefault(key, set()).add(value)
    return found


def _check_numeric(a: Document, b: Document) -> list[CandidateConflict]:
    nums_a, nums_b = _numbers_by_context(a), _numbers_by_context(b)
    out = []
    for key in nums_a.keys() & nums_b.keys():
        if not key or " " not in key:
            continue  # no context anchor - too noisy to flag
        if nums_a[key] != nums_b[key] and not (nums_a[key] & nums_b[key]):
            out.append(CandidateConflict(
                doc_a=a.id, doc_b=b.id, reason="numeric-diff",
                evidence=(
                    f"'{key}': {a.id} says {sorted(nums_a[key])}, "
                    f"{b.id} says {sorted(nums_b[key])}"
                ),
            ))
    return out


def _check_timestamp(a: Document, b: Document) -> list[CandidateConflict]:
    if a.last_modified is None or b.last_modified is None:
        return []
    gap_days = abs((a.last_modified - b.last_modified).days)
    if gap_days < STALENESS_DAYS:
        return []
    shared = _distinctive_terms(a) & _distinctive_terms(b)
    if len(shared) < _MIN_SHARED_TERMS:
        return []
    older, newer = (a, b) if a.last_modified < b.last_modified else (b, a)
    return [CandidateConflict(
        doc_a=a.id, doc_b=b.id, reason="timestamp-staleness",
        evidence=(
            f"{older.id} is {gap_days} days older than {newer.id} but covers "
            f"overlapping topics - older statements may be superseded"
        ),
    )]


def _check_metadata(a: Document, b: Document) -> list[CandidateConflict]:
    out = []
    for key in a.metadata.keys() & b.metadata.keys():
        if key.lower() in _META_KEYS_IGNORED:
            continue
        va, vb = a.metadata[key], b.metadata[key]
        if va != vb:
            out.append(CandidateConflict(
                doc_a=a.id, doc_b=b.id, reason="metadata-mismatch",
                evidence=f"frontmatter '{key}': {a.id} says {va!r}, {b.id} says {vb!r}",
            ))
    return out


def find_candidate_conflicts(docs: list[Document]) -> list[CandidateConflict]:
    """
    Run all deterministic pre-checks over every pair of docs in the batch.
    Returns candidates only - nothing here is a confirmed contradiction, and
    nothing is ever dropped from the LLM's view because of these results.
    """
    candidates: list[CandidateConflict] = []
    for a, b in combinations(docs, 2):
        candidates.extend(_check_numeric(a, b))
        candidates.extend(_check_timestamp(a, b))
        candidates.extend(_check_metadata(a, b))
    return candidates


def format_hints(candidates: list[CandidateConflict]) -> str:
    """
    Render candidates as a prompt block for the compiler. Empty string when
    there are no candidates, so the prompt is unchanged in the common case.
    """
    if not candidates:
        return ""
    lines = [
        "\n--- AUTOMATED CONFLICT CANDIDATES ---",
        "Deterministic pre-checks flagged the following potential",
        "contradictions. For EACH one, either confirm it as a real conflict",
        "in the '## Open Conflicts' section or explicitly dismiss it there",
        "with a one-line reason. Do not ignore any of them. These are hints,",
        "not verdicts - also flag any conflicts they missed.",
    ]
    for c in candidates:
        lines.append(f"- [{c.reason}] {c.doc_a} vs {c.doc_b}: {c.evidence}")
    return "\n".join(lines) + "\n"
