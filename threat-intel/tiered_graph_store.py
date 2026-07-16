"""
Tiered hot/cold storage for the campaign graph.

Spec ref: PDF Section 10.5: "Unbounded graph growth from the 'never
forget a confirmed link' rule is addressed through tiered storage, not
by weakening that rule: a hot/active tier for recent and high-relevance
nodes in the fast primary query path, and cold archival storage for
old-but-confirmed nodes -- rarely queried, still retrievable if a
dormant pattern resurfaces." STRICT SUMMARY: "Temporal decay of any kind
governs ranking and relevance only. A confirmed malicious infrastructure
link is never functionally forgotten."

Invariants enforced BY CONSTRUCTION (each has a dedicated test):
  1. Nothing is ever deleted. Demotion moves a node's edges to the cold
     tier; there is no removal API at all on confirmed data.
  2. A node with any confirmed-malicious edge can be demoted for QUERY
     ROUTING (it leaves the hot path when dormant) but its confirmed
     edges remain retrievable and are automatically REHYDRATED into the
     hot tier the moment the node reappears in a new report -- the
     "dormant infrastructure reactivates" case (spec 7.7/9.5/10.5).
  3. The fast query path (hot_graph) is what latency-sensitive callers
     use; deep_lookup() transparently unions hot + cold for research
     queries that accept the cost.

Why this is an optimization: the live risk-scoring path's graph
operations (embedding neighborhoods, centrality candidates, ANN
rebuilds) now run over only the active working set instead of the full
historical graph, which is what keeps their cost flat as history grows
-- the same reason the spec split live regional queries from async
cross-border correlation (Section 10.5, last bullet).

REAL vs SIM: fully real networkx logic, executed and tested in this
build. The cold tier is an in-memory nx.Graph here; a production
deployment maps it to the archival Postgres shard (Section 9.4) behind
the same three-method interface.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import networkx as nx

# Nodes with no activity for this long leave the hot query path.
# Governs ROUTING ONLY -- never the underlying determination (STRICT
# SUMMARY's decay rule).
DEFAULT_DORMANCY_SECONDS = 90 * 24 * 3600


@dataclass
class TieredGraphStore:
    dormancy_seconds: int = DEFAULT_DORMANCY_SECONDS
    hot_graph: nx.Graph = field(default_factory=nx.Graph)
    _cold_graph: nx.Graph = field(default_factory=nx.Graph)
    _last_seen: dict[str, float] = field(default_factory=dict)

    # ------------------------------------------------------------ ingest

    def observe(self, node_a: str, node_b: str, *, confirmed: bool = False,
                now: float | None = None) -> None:
        """Record an edge from a new (already k-anonymized, spec 2.7)
        aggregate observation. Reappearance of a cold node rehydrates its
        entire confirmed history into the hot tier -- dormant-then-
        reactivated infrastructure is treated as the known entity it is,
        never as new/unknown (spec 9.5 temporal-decay carve-out)."""
        ts = time.time() if now is None else now
        for node in (node_a, node_b):
            if node in self._cold_graph:
                self._rehydrate(node)
            self._last_seen[node] = ts
        self.hot_graph.add_edge(node_a, node_b)
        if confirmed:
            self.hot_graph.edges[node_a, node_b]["confirmed"] = True

    def _rehydrate(self, node: str) -> None:
        for neighbor in list(self._cold_graph.neighbors(node)):
            data = dict(self._cold_graph.edges[node, neighbor])
            self.hot_graph.add_edge(node, neighbor, **data)
        self._cold_graph.remove_node(node)

    # ------------------------------------------------------------ tiering

    def demote_dormant(self, now: float | None = None) -> list[str]:
        """Move nodes with no recent activity out of the fast query path.
        Confirmed edges travel WITH the node into the cold tier -- moved,
        never dropped. Returns the demoted node list (for the operational
        health metrics the spec's monitoring philosophy expects)."""
        ts = time.time() if now is None else now
        demoted: list[str] = []
        for node in list(self.hot_graph.nodes):
            if ts - self._last_seen.get(node, ts) < self.dormancy_seconds:
                continue
            # Keep a node hot if any neighbor is still active: an active
            # cluster keeps its whole neighborhood queryable (spec 7.7's
            # "nodes belonging to any existing cluster are retained").
            if any(ts - self._last_seen.get(nb, ts) < self.dormancy_seconds
                   for nb in self.hot_graph.neighbors(node)):
                continue
            for neighbor in list(self.hot_graph.neighbors(node)):
                data = dict(self.hot_graph.edges[node, neighbor])
                self._cold_graph.add_edge(node, neighbor, **data)
            self.hot_graph.remove_node(node)
            demoted.append(node)
        return demoted

    # ------------------------------------------------------------ queries

    def deep_lookup(self) -> nx.Graph:
        """Union of hot + cold for research/dashboard queries that accept
        archival latency. Read-only composition -- mutating the returned
        graph does not touch the tiers."""
        return nx.compose(self._cold_graph, self.hot_graph)

    def confirmed_edge_exists(self, node_a: str, node_b: str) -> bool:
        """A confirmed link answers True regardless of which tier holds it
        -- the literal 'never functionally forgotten' guarantee."""
        for g in (self.hot_graph, self._cold_graph):
            if g.has_edge(node_a, node_b) and g.edges[node_a, node_b].get("confirmed"):
                return True
        return False
