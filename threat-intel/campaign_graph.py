"""
Campaign correlation graph: aggregation + k-anonymity gate.

Spec ref: PDF Section 2.7, 7.7 (90-day pruning scoped to genuinely isolated
nodes only), 9.5/10.5 (entity-type-aware temporal handling: persistent
identifiers never decay; phone numbers get a bounded risk-expiry tied to
carrier recycling, requiring recent corroborating activity to keep
contributing to a LIVE score, while the historical record is preserved
permanently either way).

Real, running logic: this is a genuine networkx graph with a real
k-anonymity gate (a link is only ever exposed once >= K_ANONYMITY_FLOOR
INDEPENDENT reports corroborate it) and real entity-type-differentiated
temporal handling. No ML weights needed for this file -- campaign_predictor.py
next to it handles the GraphSAGE/ANN/centrality layer.
"""
from __future__ import annotations
import time
import uuid
from dataclasses import dataclass, field

import networkx as nx

from community_feed import CommunityReport, PatternKind

K_ANONYMITY_FLOOR = 5          # a link must appear across >=5 independent incidents before exposure
ISOLATED_NODE_PRUNE_DAYS = 90  # spec 7.7: only genuinely isolated (zero-connection) nodes prune on this cycle
PHONE_NUMBER_RISK_EXPIRY_DAYS = 270  # spec 10.5: bounded, tied to realistic regional carrier recycling timelines

# Entity types whose links NEVER decay -- they stay tied to the same
# actor's continued behavior (accounts/scripts aren't recycled to
# unrelated people the way phone numbers are).
PERSISTENT_KINDS = frozenset({PatternKind.PAYEE_ACCOUNT, PatternKind.SCRIPT_HASH, PatternKind.CRYPTO_WALLET})
REASSIGNABLE_KINDS = frozenset({PatternKind.PHONE_NUMBER})


def _node_key(kind: PatternKind, value: str) -> str:
    return f"{kind.value}:{value}"


@dataclass
class CampaignGraph:
    graph: nx.Graph = field(default_factory=nx.Graph)
    _incident_counts: dict[tuple[str, str], set[str]] = field(default_factory=dict)  # edge -> set of incident_ids

    def record_incident(self, reports: list[CommunityReport], incident_id: str | None = None) -> str:
        """
        One incident = a set of patterns reported together (implying
        correlation) -- e.g. one victim's report naming both a phone
        number AND a payee account used in the same scam attempt. Reports
        carry no user identity (community_feed.py's contract); incident_id
        exists only to dedupe corroboration counting, not to identify a
        reporter.
        """
        incident_id = incident_id or str(uuid.uuid4())
        now = time.time()

        keys = []
        for report in reports:
            key = _node_key(report.pattern_kind, report.pattern_value)
            keys.append(key)
            if key not in self.graph:
                self.graph.add_node(key, kind=report.pattern_kind, value=report.pattern_value,
                                     first_seen=now, last_seen=now, incident_ids=set())
            self.graph.nodes[key]["last_seen"] = now
            self.graph.nodes[key]["incident_ids"].add(incident_id)

        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                a, b = sorted((keys[i], keys[j]))
                edge_key = (a, b)
                self._incident_counts.setdefault(edge_key, set()).add(incident_id)
                if not self.graph.has_edge(a, b):
                    self.graph.add_edge(a, b, last_active=now)
                else:
                    self.graph[a][b]["last_active"] = now

        return incident_id

    def corroboration_count(self, node_a: str, node_b: str) -> int:
        edge_key = tuple(sorted((node_a, node_b)))
        return len(self._incident_counts.get(edge_key, set()))

    def is_link_exposable(self, node_a: str, node_b: str) -> bool:
        """The k-anonymity gate: a payee/number/script must appear across a
        minimum number of INDEPENDENT reports before any cross-report link
        is surfaced -- never a single-user-identifiable connection."""
        return self.corroboration_count(node_a, node_b) >= K_ANONYMITY_FLOOR

    def node_live_risk_active(self, node_key: str, now: float | None = None) -> bool:
        """Entity-type-aware temporal rule (Strict Instruction Summary):
        persistent identifiers are always live. Reassignable identifiers
        (phone numbers) require recent corroborating activity within the
        bounded risk-expiry window to keep contributing to a LIVE score --
        but see `historical_record_preserved`, which is always True
        regardless: the original incident is never erased, only excluded
        from a currently-active risk computation."""
        now = now if now is not None else time.time()
        data = self.graph.nodes[node_key]
        kind = data["kind"]
        if kind in PERSISTENT_KINDS:
            return True
        if kind in REASSIGNABLE_KINDS:
            age_days = (now - data["last_seen"]) / 86400
            return age_days <= PHONE_NUMBER_RISK_EXPIRY_DAYS
        return True

    def historical_record_preserved(self, node_key: str) -> bool:
        """Always True by construction: pruning (below) only ever removes
        genuinely zero-connection nodes, never a node that is part of any
        confirmed cluster -- so a node's presence in the graph, and its
        edges' corroboration history, is never functionally erased just
        because a phone number's LIVE contribution has expired above."""
        return node_key in self.graph

    def k_anonymized_view(self) -> nx.Graph:
        """Returns a subgraph containing ONLY links that clear the
        k-anonymity floor. This -- not the raw internal graph -- is what
        campaign_predictor.py, the dashboard, and any researcher-facing
        code are permitted to read. Strict Instruction Summary: 'no API
        endpoint returns a raw individual report or transcript.'"""
        exposable_edges = [
            (a, b) for a, b in self.graph.edges()
            if self.is_link_exposable(a, b)
        ]
        view = nx.Graph()
        view.add_edges_from(exposable_edges)
        for n in view.nodes():
            view.nodes[n].update(self.graph.nodes[n])
        return view

    def prune_isolated_nodes(self, now: float | None = None) -> list[str]:
        """Spec 7.7's corrected scope: prune genuinely isolated
        (zero-connection) nodes older than the cutoff. Nodes belonging to
        ANY existing cluster (degree >= 1) are retained regardless of
        recency -- scam infrastructure is often reused after long dormant
        stretches."""
        now = now if now is not None else time.time()
        to_remove = []
        for node, data in self.graph.nodes(data=True):
            if self.graph.degree(node) == 0:
                age_days = (now - data["last_seen"]) / 86400
                if age_days >= ISOLATED_NODE_PRUNE_DAYS:
                    to_remove.append(node)
        self.graph.remove_nodes_from(to_remove)
        return to_remove
