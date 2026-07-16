"""
Real FAISS ANN backend for campaign-cluster matching (GPU or CPU).

Spec ref: PDF Section 2.7 (FAISS/HNSW ANN) and Section 9.5 (recall over
latency). REAL swap-in behind the exact query() interface of
threat-intel/ann_hnsw.py's HNSWIndex.

=== REAL vs SIM boundary ===
- With `faiss` installed: real faiss.IndexHNSWFlat search.
- Without it (this sandbox): build_faiss_or_fallback() returns the tested
  pure-Python HNSWIndex. Identical result shapes either way.

See docs/REAL_MODELS_SETUP.md.
"""
from __future__ import annotations

import numpy as np

from ann_hnsw import HNSWIndex, HNSWMatch, build_hnsw


def _faiss_available() -> bool:
    try:
        import faiss  # noqa: F401
        return True
    except Exception:
        return False


class FaissANNIndex:
    """Real FAISS HNSW index, same interface as HNSWIndex."""

    def __init__(self, dim: int, m: int = 12, ef_search: int = 64, ef_construction: int = 100):
        import faiss
        self._dim = dim
        self._faiss = faiss
        self._m = m
        self._index = faiss.IndexHNSWFlat(dim, m)
        self._index.hnsw.efSearch = ef_search
        self._index.hnsw.efConstruction = ef_construction
        self._ids: list[str] = []
        self._pending: list[np.ndarray] = []
        self._built = False

    def add(self, node_id: str, vector: np.ndarray) -> None:
        self._ids.append(node_id)
        self._pending.append(np.asarray(vector, dtype=np.float32))
        self._built = False

    def _ensure_built(self) -> None:
        if self._built or not self._pending:
            return
        mat = np.vstack(self._pending).astype(np.float32)
        self._index = self._faiss.IndexHNSWFlat(self._dim, self._m)
        self._index.add(mat)
        self._built = True

    def query(self, vector: np.ndarray, top_k: int = 5) -> list[HNSWMatch]:
        if not self._ids:
            return []
        self._ensure_built()
        q = np.asarray(vector, dtype=np.float32).reshape(1, -1)
        distances, indices = self._index.search(q, min(top_k, len(self._ids)))
        out: list[HNSWMatch] = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0:
                continue
            out.append(HNSWMatch(node_id=self._ids[int(idx)], distance=float(dist) ** 0.5))
        return out


def build_faiss_or_fallback(embeddings: dict[str, np.ndarray], **kwargs: object):
    """Real FAISS if installed; otherwise the tested HNSWIndex."""
    if not embeddings:
        return build_hnsw(embeddings, **kwargs)
    if _faiss_available():
        dim = len(next(iter(embeddings.values())))
        index = FaissANNIndex(dim)
        for node_id, vec in embeddings.items():
            index.add(node_id, vec)
        return index
    return build_hnsw(embeddings, **kwargs)
