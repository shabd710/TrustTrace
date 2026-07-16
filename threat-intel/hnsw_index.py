"""Hierarchical Navigable Small World (HNSW) approximate-nearest-neighbor index.

Spec ref: PDF Target Environment / Section 2.7 ("New reports are matched
against existing clusters via an approximate-nearest-neighbor index
(FAISS/HNSW) over those embeddings -- real millisecond-scale lookup, as
opposed to brute-force cosine similarity across the full graph") and
Section 9.5 ("Tuning FAISS/HNSW parameters toward recall over raw
latency ... a missed campaign cluster has real cost").

REAL vs SIM: this is a REAL, from-scratch HNSW implementation (the actual
Malkov & Yashunin algorithm: multi-layer navigable small-world graphs,
greedy descent through upper layers, beam search with ef candidates at
layer 0), executed and verified in this build -- recall@10 is measured
against exact brute-force ground truth in tests/test_scale.py and must
clear 0.90, and single-query latency on a 2,000-vector index is asserted
to beat brute force. It is NOT FAISS: a production deployment at
millions of nodes should still swap in faiss.IndexHNSWFlat (same query()
contract, kept deliberately identical to campaign_predictor.ANNIndex),
which adds SIMD-optimized distance kernels and years of hardening this
reference cannot. What this file removes is the previous brute-force
O(N) scan as the only executable option -- this scales O(log N)-ish per
query, which is the difference between a lookup path that survives a
community feed with millions of reports and one that does not.

Recall-over-latency posture (spec 9.5) is the default: ef_search=64,
M=16 -- tuned generously for recall; profiling discipline (spec 3.5)
governs any change.
"""
from __future__ import annotations

import heapq
import math
import random
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class HNSWMatch:
    node_id: str
    similarity: float  # cosine similarity, higher = closer


@dataclass
class _Node:
    node_id: str
    vector: np.ndarray                       # L2-normalized at insert
    level: int
    neighbors: list[list[int]] = field(default_factory=list)  # per layer -> internal ids


class HNSWIndex:
    """Cosine-similarity HNSW. query() contract matches campaign_predictor.ANNIndex."""

    def __init__(
        self,
        m: int = 16,
        ef_construction: int = 200,
        ef_search: int = 64,
        seed: int = 0x7A57,
    ) -> None:
        self._m = m                        # max neighbors per node per layer (2*m at layer 0)
        self._ef_construction = ef_construction
        self._ef_search = ef_search
        self._level_mult = 1.0 / math.log(m)
        self._rng = random.Random(seed)    # deterministic level assignment: reproducible builds
        self._nodes: list[_Node] = []
        self._id_to_internal: dict[str, int] = {}
        self._entry_point: int | None = None
        self._max_level: int = -1

    # ------------------------------------------------------------------ build

    def add(self, node_id: str, vector: np.ndarray) -> None:
        if node_id in self._id_to_internal:
            raise ValueError(f"duplicate node_id: {node_id}")
        v = np.asarray(vector, dtype=np.float64)
        norm = float(np.linalg.norm(v))
        if norm == 0.0:
            raise ValueError("zero vector cannot be indexed under cosine similarity")
        v = v / norm

        level = int(-math.log(self._rng.random()) * self._level_mult)
        node = _Node(node_id=node_id, vector=v, level=level,
                     neighbors=[[] for _ in range(level + 1)])
        internal = len(self._nodes)
        self._nodes.append(node)
        self._id_to_internal[node_id] = internal

        if self._entry_point is None:
            self._entry_point = internal
            self._max_level = level
            return

        ep = self._entry_point
        # Greedy descent through layers above the new node's level.
        for layer in range(self._max_level, level, -1):
            ep = self._greedy_closest(v, ep, layer)

        # Insert with beam search from min(level, max_level) down to 0.
        for layer in range(min(level, self._max_level), -1, -1):
            candidates = self._search_layer(v, [ep], layer, self._ef_construction)
            max_conn = self._m * 2 if layer == 0 else self._m
            selected = self._select_neighbors(candidates, max_conn)
            node.neighbors[layer] = [c for _, c in selected]
            for _, c in selected:
                nbrs = self._nodes[c].neighbors[layer]
                nbrs.append(internal)
                if len(nbrs) > max_conn:
                    # Re-trim the neighbor's connections to its best max_conn.
                    scored = [(self._sim(self._nodes[c].vector, self._nodes[i].vector), i)
                              for i in nbrs]
                    self._nodes[c].neighbors[layer] = [
                        i for _, i in heapq.nlargest(max_conn, scored)
                    ]
            ep = candidates[0][1] if candidates else ep

        if level > self._max_level:
            self._max_level = level
            self._entry_point = internal

    # ------------------------------------------------------------------ query

    def query(self, vector: np.ndarray, top_k: int = 5) -> list[HNSWMatch]:
        if self._entry_point is None:
            return []
        v = np.asarray(vector, dtype=np.float64)
        norm = float(np.linalg.norm(v))
        if norm == 0.0:
            return []
        v = v / norm

        ep = self._entry_point
        for layer in range(self._max_level, 0, -1):
            ep = self._greedy_closest(v, ep, layer)

        ef = max(self._ef_search, top_k)
        candidates = self._search_layer(v, [ep], 0, ef)
        best = heapq.nlargest(top_k, candidates)
        return [HNSWMatch(node_id=self._nodes[i].node_id, similarity=s) for s, i in best]

    def __len__(self) -> int:
        return len(self._nodes)

    # -------------------------------------------------------------- internals

    @staticmethod
    def _sim(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b))  # vectors pre-normalized

    def _greedy_closest(self, v: np.ndarray, start: int, layer: int) -> int:
        current = start
        current_sim = self._sim(v, self._nodes[current].vector)
        improved = True
        while improved:
            improved = False
            for nb in self._nodes[current].neighbors[layer]:
                s = self._sim(v, self._nodes[nb].vector)
                if s > current_sim:
                    current, current_sim = nb, s
                    improved = True
        return current

    def _search_layer(
        self, v: np.ndarray, entry_points: list[int], layer: int, ef: int
    ) -> list[tuple[float, int]]:
        """Beam search: returns up to ef (similarity, internal_id), best-first."""
        visited: set[int] = set(entry_points)
        # candidates: max-heap by sim (negate); results: min-heap of kept best.
        candidates: list[tuple[float, int]] = []
        results: list[tuple[float, int]] = []
        for ep in entry_points:
            s = self._sim(v, self._nodes[ep].vector)
            heapq.heappush(candidates, (-s, ep))
            heapq.heappush(results, (s, ep))
        while candidates:
            neg_s, current = heapq.heappop(candidates)
            if len(results) >= ef and -neg_s < results[0][0]:
                break  # best remaining candidate can't improve the result set
            for nb in self._nodes[current].neighbors[layer]:
                if nb in visited:
                    continue
                visited.add(nb)
                s = self._sim(v, self._nodes[nb].vector)
                if len(results) < ef or s > results[0][0]:
                    heapq.heappush(candidates, (-s, nb))
                    heapq.heappush(results, (s, nb))
                    if len(results) > ef:
                        heapq.heappop(results)
        return sorted(results, reverse=True)

    def _select_neighbors(
        self, candidates: list[tuple[float, int]], max_conn: int
    ) -> list[tuple[float, int]]:
        """Simple top-M selection (HNSW's SELECT-NEIGHBORS-SIMPLE variant)."""
        return heapq.nlargest(max_conn, candidates)
