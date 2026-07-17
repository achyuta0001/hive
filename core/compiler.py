"""
Compiler: takes a batch of canonical Documents that overlap/relate to each
other and synthesizes ONE merged markdown wiki page.

This is the only stage in the pipeline that genuinely needs an LLM.
Provider is swappable: "ollama" (free, local, dev default) or "claude"
(better quality, use once you're validating against real pilot data).
"""

from __future__ import annotations
import json
import os
import urllib.request
from pathlib import Path

from core.canonical import Document
from core.precheck import find_candidate_conflicts, format_hints

NVIDIA_NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

WIKI_DIR = Path(__file__).parent.parent / "wiki"

SYSTEM_PROMPT = """You are a knowledge compiler. You will be given several \
source documents that overlap or relate to the same topic. Merge them into \
ONE coherent markdown wiki page.

Rules:
- Do not lose any factual detail present in the sources.
- Every source document must get its own "## <Title>" section. Immediately
  below each such heading, add a line of the exact form:
  *Source: `<source id>`*
  using the source id exactly as given in the "--- SOURCE: <id> ---" marker.
- You MUST include exactly one "## Open Conflicts" section near the bottom.
  If sources contradict each other, do NOT silently pick one - flag the
  disagreement and which source it came from. If there are no
  contradictions, the section must still be present, containing only the
  text "None found."
- You MUST include exactly one "## Sources" section at the very bottom,
  listing every source id (the exact ids from the "--- SOURCE: <id> ---"
  markers) as a markdown list, one per line.
- Write in clear, neutral, documentation style.
- Do not omit, rename, or reword the "## Open Conflicts" or "## Sources"
  headings - they must appear verbatim.
"""


def _call_ollama(prompt: str, model: str = "llama3.1:8b") -> str:
    import ollama
    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    return response["message"]["content"]


def _call_claude(prompt: str, model: str = "claude-haiku-4-5-20251001") -> str:
    import anthropic
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _call_nvidia(prompt: str, model: str = "nvidia/nemotron-3-super-120b-a12b") -> str:
    api_key = os.environ.get("NVIDIA_NIM_API_KEY") or os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError("NVIDIA_NIM_API_KEY (or NVIDIA_API_KEY) is not set")

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }).encode("utf-8")

    request = urllib.request.Request(
        NVIDIA_NIM_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        result = json.loads(response.read())
    return result["choices"][0]["message"]["content"]


def _build_prompt(docs: list[Document]) -> str:
    parts = [f"Merge these {len(docs)} source documents into one wiki page:\n"]
    for doc in docs:
        parts.append(f"--- SOURCE: {doc.id} ---\nTitle: {doc.title}\n\n{doc.content}\n")
    return "\n".join(parts)


def _validate_output(docs: list[Document], merged: str) -> None:
    for doc in docs:
        if doc.id not in merged:
            raise ValueError(f"compiled output is missing source: {doc.id}")
    if "## Open Conflicts" not in merged:
        raise ValueError("compiled output is missing the '## Open Conflicts' section")
    if "## Sources" not in merged:
        raise ValueError("compiled output is missing the '## Sources' section")


def compile_docs(docs: list[Document], topic_slug: str, provider: str = "ollama") -> Path:
    """
    Compile a batch of related Documents into one wiki page.
    provider: "ollama" (free/local, weak at conflict-flagging), "claude",
    or "nvidia" (NVIDIA NIM, e.g. nemotron-3-super-120b-a12b — validated as
    the first provider to reliably produce Open Conflicts + Sources sections).
    Returns the path to the written wiki page.
    """
    if not docs:
        raise ValueError("compile_docs called with an empty document list")

    prompt = _build_prompt(docs)

    # Deterministic pre-checks: point the LLM at candidate contradictions it
    # must confirm or dismiss in ## Open Conflicts. Hints only — nothing is
    # resolved or suppressed here, and the prompt is unchanged when the batch
    # has no candidates.
    hints = format_hints(find_candidate_conflicts(docs))
    if hints:
        prompt += "\n" + hints

    if provider == "ollama":
        merged = _call_ollama(prompt)
    elif provider == "claude":
        merged = _call_claude(prompt)
    elif provider == "nvidia":
        merged = _call_nvidia(prompt)
    else:
        raise ValueError(f"unknown provider: {provider}")

    _validate_output(docs, merged)

    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    out_path = WIKI_DIR / f"{topic_slug}.md"
    out_path.write_text(merged, encoding="utf-8")
    return out_path
