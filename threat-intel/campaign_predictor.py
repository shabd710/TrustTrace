"""
Campaign cluster prediction: inductive embeddings + ANN matching + centrality.

Spec ref: PDF Section 2.7, 8.5/9.5 (bounded-depth/PinSAGE-style random-walk
neighbor sampling), 9.5 (personalized PageRank seeded from known-bad
nodes), Strict Instruction Summary ("never point-to-point pathfinding
search... there is no single start/goal pair in this problem" -- except
the narrowly-scoped dashboard BFS carve-out in 9.5, implemented separately
in dashboard-facing code, NOT here in the core prediction path).

REAL vs SIM, stated plainly:
  - Real GraphSAGE uses PyTorch Geometric with LEARNED neighborhood-
    aggregation weight matrices, trained on a large labeled graph. No
    torch/PyG and no training data exist in this sandbox. What's
    implemented here is a genuine, un-learned (fixed-aggregator) inductive
    embedding: mean-aggregation over a bounded-depth, fixed-size random
    walk neighborhood sample (the PinSAGE-style sampling strategy spec 8.5
    calls for), which is inductive by the same structural property real
    GraphSAGE relies on -- it only reads local graph structure, so it
    genuinely CAN embed a node it has never seen retrained on, unlike a
    transductive GCN. It just isn't LEARNED; a production swap-in trains
    real aggregation weights on top of this exact sampling strategy.
  - Real ANN matching uses FAISS/HNSW for real sub-linear approximate
    nearest-neighbor search at scale. Not installed here (no network).
    What's implemented is a small, real, brute-force-but-vectorized
    (numpy) nearest-neighbor search -- correct results, O(n) instead of
    FAISS/HNSW's O(log n), which is the honest tradeoff at this node
    count. The `ANNIndex` interface is what a real FAISS/HNSW-backed
    class would implement identically.
  - Betweenness centrality and personalized PageRank ARE real here --
    networkx implements both directly, no stand-in needed.
"""
from __future__ import annotations
import random
from dataclasses import dataclass

import networkx as nx
import numpy as np

RANDOM_WALK_LENGTH = 4
RANDOM_WALK_COUNT_PER_NODE = 8       # PinSAGE-style: bounded, fixed-size sampling, not full neighborhood
EMBEDDING_DIM = 16


def _sample_neighborhood(graph: nx.Graph, node: str, rng: random.Random) -> list[str]:
    """Bounded-depth, fixed-size random-walk neighborhood sample (PinSAGE
    approach per spec 9.5) -- deliberately NOT full-neighborhood
    aggregation, which is what avoids the neighborhood-explosion problem
    on high-degree hub nodes spec 8.5 names."""
    sampled = []
    for _ in range(RANDOM_WALK_COUNT_PER_NODE):
        current = node
        for _ in range(RANDOM_WALK_LENGTH):
            neighbors = list(graph.neighbors(current))
            if not neighbors:
                break
            current = rng.choice(neighbors)
            sampled.append(current)
    return sampled


def _feature_vector(graph: nx.Graph, node: str) -> np.ndarray:
    """Structural features only (degree, clustering coefficient, a
    deterministic hash-based positional component) -- no learned weights,
    consistent with the "un-learned aggregator" honesty note above."""
    degree = graph.degree(node)
    clustering = nx.clustering(graph, node) if graph.degree(node) > 1 else 0.0
    # deterministic pseudo-random positional features from a hash of the
    # node id, standing in for what would otherwise be learned embedding
    # dimensions -- gives distinct nodes distinct vectors without claiming
    # any semantic meaning for individual dimensions.
    h = abs(hash(node))
    rng = np.random.default_rng(h % (2**32))
    positional = rng.normal(0, 1, size=EMBEDDING_DIM - 2)
    return np.concatenate([[degree, clustering], positional])


def compute_embeddings(graph: nx.Graph, seed: int = 42) -> dict[str, np.ndarray]:
    """
    Inductive embedding per node: mean-aggregate the feature vectors of a
    PinSAGE-style sampled neighborhood with the node's own feature vector.
    Genuinely inductive -- a brand-new node just needs ITS OWN local
    neighborhood sampled, not a full-graph retrain, which is the exact
    "a brand-new report just arrived, does it belong to a known cluster"
    property spec 2.7 requires.
    """
    rng = random.Random(seed)
    embeddings = {}
    for node in graph.nodes():
        own = _feature_vector(graph, node)
        neighborhood = _sample_neighborhood(graph, node, rng)
        if neighborhood:
            neighbor_vecs = np.stack([_feature_vector(graph, n) for n in neighborhood])
            agg = neighbor_vecs.mean(axis=0)
        else:
            agg = np.zeros_like(own)
        embeddings[node] = (own + agg) / 2.0
    return embeddings


@dataclass
class ANNMatch:
    node: str
    distance: float


class ANNIndex:
    """Brute-force-but-vectorized nearest-neighbor index -- see module
    docstring's honest FAISS/HNSW substitution note. Same query interface
    a real FAISS/HNSW-backed implementation would expose."""

    def __init__(self, embeddings: dict[str, np.ndarray]):
        self._keys = list(embeddings.keys())
        self._matrix = np.stack([embeddings[k] for k in self._keys]) if embeddings else np.empty((0, EMBEDDING_DIM))

    def query(self, vector: np.ndarray, top_k: int = 5) -> list[ANNMatch]:
        if len(self._keys) == 0:
            return []
        dists = np.linalg.norm(self._matrix - vector, axis=1)
        order = np.argsort(dists)[:top_k]
        return [ANNMatch(self._keys[i], float(dists[i])) for i in order]


def find_closest_cluster(graph: nx.Graph, new_node: str, embeddings: dict[str, np.ndarray] | None = None, top_k: int = 5) -> list[ANNMatch]:
    """New-report-arrives entry point: embed (or reuse an existing
    embedding for) new_node, then ANN-match it against every other node's
    embedding to find its closest existing cluster."""
    embeddings = embeddings if embeddings is not None else compute_embeddings(graph)
    if new_node not in embeddings:
        raise ValueError(f"{new_node} not present in graph -- embed it via compute_embeddings first")
    index = ANNIndex({k: v for k, v in embeddings.items() if k != new_node})
    return index.query(embeddings[new_node], top_k=top_k)


def betweenness_chokepoints(graph: nx.Graph, top_k: int = 10) -> list[tuple[str, float]]:
    """
    Real betweenness centrality (networkx, no stand-in needed) --
    identifies reused chokepoints/cash-out hubs, per spec 2.7's explicit
    rejection of pathfinding (A*/bidirectional) for this question: there
    is no single start/goal pair, this is a structural-position question.
    """
    scores = nx.betweenness_centrality(graph)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]


def personalized_suspicion_pagerank(graph: nx.Graph, known_bad_nodes: list[str], top_k: int = 10) -> list[tuple[str, float]]:
    """
    Spec 9.5: personalized (topic-sensitive) PageRank seeded from the
    known-bad node set, propagating suspicion weighted by connection
    strength to already-confirmed malicious nodes. Real networkx
    implementation, not a stand-in.
    """
    present = [n for n in known_bad_nodes if n in graph]
    if not present:
        return []
    personalization = {n: (1.0 if n in present else 0.0) for n in graph.nodes()}
    scores = nx.pagerank(graph, personalization=personalization, alpha=0.85)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
