"""
Offline tests for core/clustering.py — pure math, no network, no DB.

Run: python -m pytest tests/test_clustering.py  (or python tests/test_clustering.py)
"""

from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.canonical import Document
from core.clustering import cluster_docs


def _doc(doc_id: str, title: str) -> Document:
    return Document(id=doc_id, source="markdown", title=title, content="body")


def _key(doc: Document) -> str:
    return f"{doc.source}::{doc.id}"


def test_empty_input():
    assert cluster_docs([], {}) == []


def test_doc_without_embedding_excluded():
    a, b = _doc("a", "Alpha"), _doc("b", "Beta")
    clusters = cluster_docs([a, b], {_key(a): [1.0, 0.0]}, threshold=0.7)
    members = [m.id for _, ms in clusters for m in ms]
    assert members == ["a"]


def test_similar_docs_group_dissimilar_split():
    a, b, c = _doc("a", "Deploy Guide"), _doc("b", "Deploy Steps"), _doc("c", "Auth Notes")
    embeddings = {
        _key(a): [1.0, 0.0],
        _key(b): [0.99, 0.1],   # ~0.995 similarity to a
        _key(c): [0.0, 1.0],    # orthogonal to both
    }
    clusters = cluster_docs([a, b, c], embeddings, threshold=0.7)
    assert len(clusters) == 2
    sizes = sorted(len(ms) for _, ms in clusters)
    assert sizes == [1, 2]


def test_threshold_controls_grouping():
    a, b = _doc("a", "Alpha"), _doc("b", "Beta")
    embeddings = {_key(a): [1.0, 0.0], _key(b): [1.0, 1.0]}  # cosine ~0.707
    loose = cluster_docs([a, b], embeddings, threshold=0.5)
    strict = cluster_docs([a, b], embeddings, threshold=0.9)
    assert len(loose) == 1
    assert len(strict) == 2


def test_slug_from_dominant_title_slugified():
    a = _doc("a", "Deployment & Release Process!")
    clusters = cluster_docs([a], {_key(a): [1.0, 0.0]}, threshold=0.7)
    assert clusters[0][0] == "deployment-release-process"


def test_slug_collision_gets_suffix():
    a, b = _doc("a", "Notes"), _doc("b", "Notes")
    embeddings = {_key(a): [1.0, 0.0], _key(b): [0.0, 1.0]}  # two clusters, same title
    slugs = sorted(slug for slug, _ in cluster_docs([a, b], embeddings, threshold=0.7))
    assert slugs == ["notes", "notes-2"]


def test_clusters_sorted_by_slug_members_keep_input_order():
    a, b, c = _doc("a", "Zulu"), _doc("b", "Alpha"), _doc("c", "Zulu Twin")
    embeddings = {
        _key(a): [1.0, 0.0],
        _key(b): [0.0, 1.0],
        _key(c): [0.99, 0.1],
    }
    clusters = cluster_docs([a, b, c], embeddings, threshold=0.7)
    assert [slug for slug, _ in clusters] == sorted(slug for slug, _ in clusters)
    zulu_members = next(ms for slug, ms in clusters if len(ms) == 2)
    assert [m.id for m in zulu_members] == ["a", "c"]  # input order preserved


def test_zero_vector_never_links():
    a, b = _doc("a", "Alpha"), _doc("b", "Beta")
    embeddings = {_key(a): [0.0, 0.0], _key(b): [1.0, 0.0]}
    clusters = cluster_docs([a, b], embeddings, threshold=0.5)
    assert len(clusters) == 2


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
