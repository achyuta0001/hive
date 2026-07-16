"""
Clustering: groups canonical Documents into topics via cosine similarity
over precomputed embeddings + connected components (pure Python, no deps).

Each cluster gets a slug derived from its dominant document (the member
closest to the cluster centroid), so a sync can compile one wiki page per
real topic instead of one naive batch.
"""

from __future__ import annotations
import math
import re

from core.canonical import Document


def _embedding_key(doc: Document) -> str:
    return f"{doc.source}::{doc.id}"


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _centroid(vectors: list[list[float]]) -> list[float]:
    n = len(vectors)
    return [sum(dims) / n for dims in zip(*vectors)]


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "untitled"


def cluster_docs(
    docs: list[Document],
    embeddings: dict[str, list[float]],
    threshold: float = 0.6,
) -> list[tuple[str, list[Document]]]:
    """
    Group documents into topic clusters.

    Docs with cosine similarity >= threshold are linked; connected
    components form clusters (singletons allowed). Docs whose embedding
    key (f"{source}::{id}") is missing from `embeddings` are excluded.

    Returns (slug, members) pairs sorted by slug; members keep the input
    doc order. Slug comes from the title of the member closest to the
    cluster centroid, with -2, -3... appended on collisions.
    """
    embedded = [doc for doc in docs if _embedding_key(doc) in embeddings]
    if not embedded:
        return []

    vectors = [embeddings[_embedding_key(doc)] for doc in embedded]
    n = len(embedded)

    # Union-find over pairs above the similarity threshold.
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if _cosine_similarity(vectors[i], vectors[j]) >= threshold:
                parent[find(i)] = find(j)

    components: dict[int, list[int]] = {}
    for i in range(n):
        components.setdefault(find(i), []).append(i)

    # Name each cluster after its dominant doc, disambiguating slug clashes.
    clusters: list[tuple[str, list[Document]]] = []
    slug_counts: dict[str, int] = {}
    for indices in components.values():
        centroid = _centroid([vectors[i] for i in indices])
        dominant = max(
            indices, key=lambda i: _cosine_similarity(vectors[i], centroid)
        )
        slug = _slugify(embedded[dominant].title)
        slug_counts[slug] = slug_counts.get(slug, 0) + 1
        if slug_counts[slug] > 1:
            slug = f"{slug}-{slug_counts[slug]}"
        clusters.append((slug, [embedded[i] for i in indices]))

    clusters.sort(key=lambda pair: pair[0])
    return clusters
