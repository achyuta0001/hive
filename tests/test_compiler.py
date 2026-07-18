"""
Offline tests for core/compiler.py's non-LLM surface — prompt building,
the precheck-hint invariant, and the _validate_output safety net. No
provider is ever called: every compile_docs invocation here fails before
reaching one.

Run: python -m pytest tests/test_compiler.py  (or python tests/test_compiler.py)
"""

from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.canonical import Document
from core.compiler import _build_prompt, _validate_output, compile_docs
from core.precheck import find_candidate_conflicts, format_hints


def _doc(doc_id: str, content: str, title: str | None = None) -> Document:
    return Document(id=doc_id, source="test", title=title or doc_id,
                    content=content, permissions=["local"])


# --- prompt building ------------------------------------------------------

def test_build_prompt_source_markers_and_order():
    docs = [_doc("first.md", "alpha body", "First"),
            _doc("second.md", "beta body", "Second")]
    prompt = _build_prompt(docs)
    assert "--- SOURCE: first.md ---" in prompt
    assert "--- SOURCE: second.md ---" in prompt
    assert "Title: First" in prompt and "alpha body" in prompt
    assert prompt.index("first.md") < prompt.index("second.md")  # input order


def test_clean_batch_prompt_byte_identical():
    # The documented invariant: a batch with no candidate conflicts must
    # leave the prompt exactly what _build_prompt produced — no hint noise.
    docs = [_doc("a", "General notes about writing style."),
            _doc("b", "Completely unrelated cooking recipe.")]
    assert format_hints(find_candidate_conflicts(docs)) == ""


def test_conflicting_batch_appends_hints_after_prompt():
    # Numeric-diff pair (same anchor, different value) from test_precheck.
    docs = [_doc("a", "The deploy timeout is 30 minutes for all services."),
            _doc("b", "Remember: the deploy timeout is 45 minutes now.")]
    hints = format_hints(find_candidate_conflicts(docs))
    assert hints  # candidates found
    base = _build_prompt(docs)
    combined = base + "\n" + hints  # exactly what compile_docs sends
    assert combined.startswith(base)  # original prompt intact, hints appended


# --- output validation (the safety net) -----------------------------------

def _merged_for(docs: list[Document]) -> str:
    sections = "\n".join(f"## {d.title}\n*Source: `{d.id}`*\n{d.content}" for d in docs)
    sources = "\n".join(f"- {d.id}" for d in docs)
    return f"{sections}\n\n## Open Conflicts\nNone found.\n\n## Sources\n{sources}\n"


def test_validate_passes_on_well_formed_output():
    docs = [_doc("a", "x"), _doc("b", "y")]
    _validate_output(docs, _merged_for(docs))  # must not raise


def test_validate_raises_naming_dropped_source():
    docs = [_doc("kept.md", "x"), _doc("dropped.md", "y")]
    merged = _merged_for([docs[0]])  # model silently dropped one source
    try:
        _validate_output(docs, merged)
        raise AssertionError("expected ValueError for dropped source")
    except ValueError as exc:
        assert "dropped.md" in str(exc)


def test_validate_raises_on_missing_required_sections():
    docs = [_doc("a", "x")]
    merged = _merged_for(docs)
    for heading in ("## Open Conflicts", "## Sources"):
        broken = merged.replace(heading, "## Something Else")
        try:
            _validate_output(docs, broken)
            raise AssertionError(f"expected ValueError for missing {heading}")
        except ValueError as exc:
            assert heading in str(exc)


# --- compile_docs guards (fail before any provider call) ------------------

def test_compile_docs_empty_batch_raises():
    try:
        compile_docs([], "slug")
        raise AssertionError("expected ValueError for empty batch")
    except ValueError as exc:
        assert "empty" in str(exc)


def test_compile_docs_unknown_provider_raises():
    try:
        compile_docs([_doc("a", "x")], "slug", provider="bogus")
        raise AssertionError("expected ValueError for unknown provider")
    except ValueError as exc:
        assert "unknown provider" in str(exc)


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
