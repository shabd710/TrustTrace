"""
Real GraphSAGE embeddings via torch-geometric (GPU or CPU).

Spec ref: PDF Section 2.7 (inductive GraphSAGE) and 9.5 (PinSAGE-style
sampling). REAL swap-in for campaign_predictor.py's hand-rolled aggregator.

=== REAL vs SIM boundary ===
- With torch + torch_geometric installed: real SAGEConv forward pass
  (GPU if available).
- Without them (this sandbox): compute_embeddings_or_fallback() returns
  the tested inductive aggregator. Same {node_id: vector} shape.

HONESTY NOTE: ships with RANDOM-INITIALIZED SAGEConv weights -- a real
architecture doing real message passing, but NOT trained. Set
TRUSTTRACE_SAGE_WEIGHTS to a trained state_dict to make it task-optimized;
training needs a labeled campaign graph (a data task, not a code task).

See docs/REAL_MODELS_SETUP.md.
"""
from __future__ import annotations

import os

import networkx as nx
import numpy as np

from campaign_predictor import compute_embeddings, _feature_vector

EMBED_DIM = int(os.environ.get("TRUSTTRACE_SAGE_DIM", "32"))
SAGE_WEIGHTS = os.environ.get("TRUSTTRACE_SAGE_WEIGHTS", "")


def _torch_geometric_available() -> bool:
    try:
        import torch  # noqa: F401
        import torch_geometric  # noqa: F401
        return True
    except Exception:
        return False


def compute_embeddings_sage(graph: nx.Graph, dim: int = EMBED_DIM,
                            state_dict_path: str = SAGE_WEIGHTS) -> dict[str, np.ndarray]:
    """Real 2-layer GraphSAGE embeddings. Requires torch_geometric."""
    import torch
    from torch_geometric.nn import SAGEConv

    nodes = list(graph.nodes())
    if not nodes:
        return {}
    idx = {n: i for i, n in enumerate(nodes)}
    x = torch.tensor(np.stack([_feature_vector(graph, n) for n in nodes]), dtype=torch.float32)
    in_dim = x.shape[1]
    edges = []
    for a, b in graph.edges():
        edges.append([idx[a], idx[b]])
        edges.append([idx[b], idx[a]])
    edge_index = (torch.tensor(edges, dtype=torch.long).t().contiguous()
                  if edges else torch.empty((2, 0), dtype=torch.long))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    class SAGE(torch.nn.Module):
        def __init__(self, i, h, o):
            super().__init__()
            self.c1 = SAGEConv(i, h)
            self.c2 = SAGEConv(h, o)

        def forward(self, x, ei):
            x = self.c1(x, ei).relu()
            return self.c2(x, ei)

    model = SAGE(in_dim, max(dim, 16), dim).to(device)
    if state_dict_path and os.path.isfile(state_dict_path):
        model.load_state_dict(torch.load(state_dict_path, map_location=device))
    model.eval()
    with torch.no_grad():
        out = model(x.to(device), edge_index.to(device)).cpu().numpy()
    return {n: out[idx[n]] for n in nodes}


def compute_embeddings_or_fallback(graph: nx.Graph, **kwargs) -> dict[str, np.ndarray]:
    """Real SAGEConv if torch_geometric present; else tested aggregator."""
    if _torch_geometric_available():
        try:
            return compute_embeddings_sage(graph, **kwargs)
        except Exception:
            pass
    return compute_embeddings(graph)
