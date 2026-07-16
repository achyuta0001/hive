"""
Embeddings: turn canonical Documents into vectors for topic clustering.

Cost principle: this module only ever receives documents that passed
core/hash_diff.py's filter_changed (or that genuinely need re-embedding).
Never call it on content the hash-diff layer already marked unchanged.
"""

from __future__ import annotations
import json
import os
import urllib.request

from core.canonical import Document

NVIDIA_EMBED_URL = "https://integrate.api.nvidia.com/v1/embeddings"

_MAX_CHARS = 8000


def _doc_key(doc: Document) -> str:
    return f"{doc.source}::{doc.id}"


def _embed_nvidia(texts: list[str], model: str = "nvidia/nv-embedqa-e5-v5") -> list[list[float]]:
    api_key = os.environ.get("NVIDIA_NIM_API_KEY") or os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError("NVIDIA_NIM_API_KEY (or NVIDIA_API_KEY) is not set")

    payload = json.dumps({
        "input": texts,
        "model": model,
        "input_type": "passage",
        "encoding_format": "float",
        # Model caps input at 512 tokens; let the server truncate rather than
        # guessing a char cutoff client-side (topic signal is front-loaded).
        "truncate": "END",
    }).encode("utf-8")

    request = urllib.request.Request(
        NVIDIA_EMBED_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        result = json.loads(response.read())
    return [item["embedding"] for item in result["data"]]


def _embed_ollama(texts: list[str], model: str = "nomic-embed-text") -> list[list[float]]:
    import ollama  # client honors OLLAMA_HOST env automatically
    return [ollama.embeddings(model=model, prompt=text)["embedding"] for text in texts]


def embed_docs(docs: list[Document], provider: str = "nvidia") -> dict[str, list[float]]:
    """
    Embed a batch of Documents. Returns {"<source>::<id>": vector} for every
    doc with non-empty content; empty/whitespace-only docs are skipped.
    provider: "nvidia" (NVIDIA NIM, batched in one request) or "ollama"
    (free/local, one call per doc).
    """
    keyed = [(_doc_key(doc), doc.content[:_MAX_CHARS]) for doc in docs if doc.content.strip()]
    if not keyed:
        return {}

    texts = [text for _, text in keyed]

    if provider == "nvidia":
        vectors = _embed_nvidia(texts)
    elif provider == "ollama":
        vectors = _embed_ollama(texts)
    else:
        raise ValueError(f"unknown provider: {provider}")

    return {key: vector for (key, _), vector in zip(keyed, vectors)}
