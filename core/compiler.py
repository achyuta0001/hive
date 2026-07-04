"""
Compiler: takes a batch of canonical Documents that overlap/relate to each
other and synthesizes ONE merged markdown wiki page.

This is the only stage in the pipeline that genuinely needs an LLM.
Provider is swappable: "ollama" (free, local, dev default) or "claude"
(better quality, use once you're validating against real pilot data).
"""

from __future__ import annotations
import os
from pathlib import Path

from core.canonical import Document

WIKI_DIR = Path(__file__).parent.parent / "wiki"

SYSTEM_PROMPT = """You are a knowledge compiler. You will be given several \
source documents that overlap or relate to the same topic. Merge them into \
ONE coherent markdown wiki page.

Rules:
- Do not lose any factual detail present in the sources.
- If sources contradict each other, do NOT silently pick one - add a
  "## Open Conflicts" section at the bottom flagging the disagreement and
  which source it came from.
- Write in clear, neutral, documentation style.
- Include a "## Sources" section at the bottom listing each source id.
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


def _build_prompt(docs: list[Document]) -> str:
    parts = [f"Merge these {len(docs)} source documents into one wiki page:\n"]
    for doc in docs:
        parts.append(f"--- SOURCE: {doc.id} ---\nTitle: {doc.title}\n\n{doc.content}\n")
    return "\n".join(parts)


def compile_docs(docs: list[Document], topic_slug: str, provider: str = "ollama") -> Path:
    """
    Compile a batch of related Documents into one wiki page.
    provider: "ollama" (default, free/local) or "claude" (higher quality).
    Returns the path to the written wiki page.
    """
    if not docs:
        raise ValueError("compile_docs called with an empty document list")

    prompt = _build_prompt(docs)

    if provider == "ollama":
        merged = _call_ollama(prompt)
    elif provider == "claude":
        merged = _call_claude(prompt)
    else:
        raise ValueError(f"unknown provider: {provider}")

    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    out_path = WIKI_DIR / f"{topic_slug}.md"
    out_path.write_text(merged, encoding="utf-8")
    return out_path
