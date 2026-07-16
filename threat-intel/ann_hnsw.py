"""
HNSW approximate-nearest-neighbor index for campaign-cluster matching.

Spec ref: PDF Section 2.7: "New reports are matched against existing
clusters via an approximate-nearest-neighbor index (FAISS/HNSW) over
those embeddings -- real millisecond-scale lookup, as opposed to
brute-force cosine similarity across the full graph." Section 9.5:
"Tuning FAISS/HNSW parameters toward recall over raw latency" -- the
defaults below (ef_search=64, M=12) follow that instruction: recall
first, still sub-linear.

What this is: a genuine Hierarchical Navigable Small World graph index
(Malkov & Yashunin) -- multi-layer greedy search with best-first
candidate expansion -- implemented against numpy only, because FAISS
cannot be installed in this sandbox (network-restricted; the same
documented constraint as FastAPI). This REPLACES the brute-force numpy
scan as the default index while keeping its exact `query()` interface,
and it is the spec-correct ALGORITHM, not a stand-in for it: a production
deployment can either keep this or swap to faiss.IndexHNSWFlat behind the
same interface for its optimized C++ kernels -- the swap is now an
implementation-speed choice, not an algorithmic gap.

REAL vs SIM: fully real, executed and verified in this build --
recall@5 measured against exact brute-force ground truth (>=0.9 required
by tests/test_optimizations.py) and query latency benchmarked vs brute
force at N=3000 in eval/benchmarks.py.

Cross-layer security note: operates only on embeddings derived from the
already k-anonymized aggregate graph (Section 2.7's boundary) -- this
module never sees, and has no import path to, raw individual reports.
"""
from __future__ import annotations

import heapq
import math
import random
from dataclasses import dataclass

import numpy as np


@dataclass
class HNSWMatch:
    node_id: str
    distance: float


class HNSWIndex:
    """Hierarchical Navigable Small World index.

    Parameters follow the recall-over-latency instruction (spec 9.5):
      M          -- max neighbors per node per layer (graph degree)
      ef_build   -- candidate-list width during construction
      ef_search  -- candidate-list width during query (recall knob)
    """

    def __init__(self, dim: int, m: int = 12, ef_build: int = 100,
                 ef_search: int = 64, seed: int = 42):
        self._dim = dim
        self._m = m
        self._m0 = 2 * m               # layer-0 degree, per the paper
        self._ef_build = ef_build
        self.ef_search = ef_search
        self._level_mult = 1.0 / math.log(m)
        self._rng = random.Random(seed)

        self._vectors: list[np.ndarray] = []
        self._ids: list[str] = []
        # neighbors[layer][node_index] -> list[int]
        self._neighbors: list[dict[int, list[int]]] = []
        self._entry_point: int | None = None
        self._max_layer = -1

    # ---------------------------------------------------------------- build

    def add(self, node_id: str, vector: np.ndarray) -> None:
        vec = np.asarray(vector, dtype=np.float64)
        idx = len(self._vectors)
        self._vectors.append(vec)
        self._ids.append(node_id)

        node_layer = int(-math.log(max(self._rng.random(), 1e-12)) * self._level_mult)

        while self._max_layer < node_layer:
            self._neighbors.append({})
            self._max_layer += 1
        for layer in range(node_layer + 1):
            self._neighbors[layer].setdefault(idx, [])

        if self._entry_point is None:
            self._entry_point = idx
            return

        # Greedy descent from the top layer to node_layer+1.
        curr = self._entry_point
        for layer in range(self._max_layer, node_layer, -1):
            curr = self._greedy_closest(vec, curr, layer)

        # Insert with best-first search on layers node_layer..0.
        for layer in range(min(node_layer, self._max_layer), -1, -1):
            candidates = self._search_layer(vec, curr, self._ef_build, layer)
            max_deg = self._m0 if layer == 0 else self._m
            selected = [i for _, i in heapq.nsmallest(max_deg, candidates)]
            self._neighbors[layer][idx] = list(selected)
            for other in selected:
                links = self._neighbors[layer].setdefault(other, [])
                links.append(idx)
                if len(links) > max_deg:
                    # Prune: keep the max_deg closest to `other`.
                    ov = self._vectors[other]
                    links.sort(key=lambda j: float(np.linalg.norm(self._vectors[j] - ov)))
                    del links[max_deg:]
            if candidates:
                curr = min(candidates)[1]

        # New global entry point if this node's layer is the highest.
        if node_layer >= self._max_layer:
            self._entry_point = idx

    # ---------------------------------------------------------------- search

    def _dist(self, vec: np.ndarray, idx: int) -> float:
        return float(np.linalg.norm(self._vectors[idx] - vec))

    def _greedy_closest(self, vec: np.ndarray, start: int, layer: int) -> int:
        curr, curr_d = start, self._dist(vec, start)
        improved = True
        while improved:
            improved = False
            for nb in self._neighbors[layer].get(curr, []):
                d = self._dist(vec, nb)
                if d < curr_d:
                    curr, curr_d, improved = nb, d, True
        return curr

    def _search_layer(self, vec: np.ndarray, entry: int, ef: int,
                      layer: int) -> list[tuple[float, int]]:
        """Best-first search; returns [(distance, index)] of up to ef nodes."""
        visited = {entry}
        d0 = self._dist(vec, entry)
        candidates = [(d0, entry)]              # min-heap by distance
        results = [(-d0, entry)]                # max-heap (negated) of best ef
        while candidates:
            d, node = heapq.heappop(candidates)
            if d > -results[0][0]:
                break
            for nb in self._neighbors[layer].get(node, []):
                if nb in visited:
                    continue
                visited.add(nb)
                dn = self._dist(vec, nb)
                if len(results) < ef or dn < -results[0][0]:
                    heapq.heappush(candidates, (dn, nb))
                    heapq.heappush(results, (-dn, nb))
                    if len(results) > ef:
                        heapq.heappop(results)
        return [(-nd, i) for nd, i in results]

    def query(self, vector: np.ndarray, top_k: int = 5) -> list[HNSWMatch]:
        """Same interface as the brute-force ANNIndex.query()."""
        if self._entry_point is None:
            return []
        vec = np.asarray(vector, dtype=np.float64)
        curr = self._entry_point
        for layer in range(self._max_layer, 0, -1):
            curr = self._greedy_closest(vec, curr, layer)
        found = self._search_layer(vec, curr, max(self.ef_search, top_k), 0)
        found.sort()
        return [HNSWMatch(node_id=self._ids[i], distance=d) for d, i in found[:top_k]]


def build_hnsw(embeddings: dict[str, np.ndarray], **kwargs: object) -> HNSWIndex:
    """Build an index from the same {node_id: embedding} dict
    campaign_predictor.compute_embeddings() produces."""
    if not embeddings:
        return HNSWIndex(dim=0)
    dim = len(next(iter(embeddings.values())))
    index = HNSWIndex(dim=dim, **kwargs)  # type: ignore[arg-type]
    for node_id, vec in embeddings.items():
        index.add(node_id, vec)
    return index
