"""
Tests for the optimization/power upgrades (Master revision).

Covers: Aho-Corasick Tier 0 equivalence, HNSW recall + interface,
tiered hot/cold graph invariants, centrality fallback labeling, and the
thermal governor's ladder/hysteresis/degraded-mode contract.
"""
from __future__ import annotations

import random
import string

import networkx as nx
import numpy as np
import pytest

from detection.conversation.fast_pattern_matcher import (scan_cues, scan_cues_regex_prescreen, scan_cues_aho_corasick, _naive_cue_scan)
from detection.conversation.model_cascade import route
from detection.telemetry.thermal_governor import ThermalGovernor, ThermalState

from campaign_predictor import compute_embeddings, ANNIndex
from ann_hnsw import build_hnsw
from tiered_graph_store import TieredGraphStore
from centrality_fallback import chokepoints_with_fallback


# ---------------------------------------------------------------- Tier 0 AC

ADVERSARIAL_TEXTS = [
    "",
    "act",                                   # prefix of a cue, not a match
    "act now",                               # exact cue
    "please ACT NOW and buy a GIFT CARD",    # caller lowercases; we test lowered
    "don't tell your bank, don't tell your family, keep it a secret",
    "giftcard",                              # no-space variant must NOT match
    "wire transferwire transfer",            # overlapping/adjacent occurrences
    "x" * 5000 + " urgent " + "y" * 5000,    # long benign padding
    "übergency right now bitte",             # unicode neighbors
]


def test_aho_corasick_equivalence_adversarial():
    for text in ADVERSARIAL_TEXTS:
        lowered = text.lower()
        expected = _naive_cue_scan(lowered)
        assert scan_cues(lowered) == expected, repr(text)
        assert scan_cues_regex_prescreen(lowered) == expected, repr(text)
        assert scan_cues_aho_corasick(lowered) == expected, repr(text)


def test_aho_corasick_equivalence_random_fuzz():
    rng = random.Random(3)
    cues = ["act now", "gift card", "don't tell", "urgent", "crypto",
            "this is your bank", "guaranteed return"]
    for _ in range(300):
        parts = ["".join(rng.choices(string.ascii_lowercase + " ", k=rng.randint(0, 40)))
                 for _ in range(rng.randint(1, 6))]
        if rng.random() < 0.6:
            parts.insert(rng.randrange(len(parts) + 1), rng.choice(cues))
        text = " ".join(parts).lower()
        expected = _naive_cue_scan(text)
        assert scan_cues(text) == expected
        assert scan_cues_regex_prescreen(text) == expected
        assert scan_cues_aho_corasick(text) == expected


def test_cascade_end_to_end_unchanged_semantics():
    r = route("This is your bank. Act now and buy a gift card, don't tell your family.")
    tactics = {c.tactic_id for c in r.candidates}
    assert {"authority_impersonation", "urgency_injection",
            "payment_channel_funneling", "isolation_instruction"} <= tactics


# ---------------------------------------------------------------- HNSW

def _test_graph(n: int = 400) -> nx.Graph:
    g = nx.barabasi_albert_graph(n, 3, seed=5)
    return nx.relabel_nodes(g, {i: f"n{i}" for i in g.nodes})


def test_hnsw_interface_matches_brute_force_shape():
    emb = compute_embeddings(_test_graph(120))
    idx = build_hnsw(emb)
    q = next(iter(emb.values()))
    res = idx.query(q, top_k=5)
    assert len(res) == 5
    assert all(hasattr(m, "node_id") and hasattr(m, "distance") for m in res)
    # Nearest to a stored vector must be that vector itself (distance ~0).
    assert res[0].distance == pytest.approx(0.0, abs=1e-9)


def test_hnsw_recall_at_5_vs_exact():
    emb = compute_embeddings(_test_graph(500))
    brute, hnsw = ANNIndex(emb), build_hnsw(emb)
    rng = np.random.default_rng(9)
    keys = list(emb.keys())
    hits = total = 0
    for i in range(60):
        q = emb[keys[int(rng.integers(len(keys)))]] + rng.normal(0, 0.01, len(emb[keys[0]]))
        truth = {m.node for m in brute.query(q, top_k=5)}
        got = {m.node_id for m in hnsw.query(q, top_k=5)}
        hits += len(truth & got)
        total += len(truth)
    assert hits / total >= 0.9, f"recall@5 too low: {hits/total:.3f}"


def test_hnsw_empty_index():
    assert build_hnsw({}).query(np.zeros(4)) == []


# ---------------------------------------------------------------- tiered store

def test_tiered_store_confirmed_link_never_forgotten():
    store = TieredGraphStore(dormancy_seconds=100)
    store.observe("payee-1", "victim-report-hash-a", confirmed=True, now=1000.0)
    demoted = store.demote_dormant(now=1000.0 + 101)
    assert "payee-1" in demoted
    assert "payee-1" not in store.hot_graph              # left the fast path...
    assert store.confirmed_edge_exists("payee-1", "victim-report-hash-a")  # ...never forgotten
    assert store.deep_lookup().has_edge("payee-1", "victim-report-hash-a")


def test_tiered_store_rehydrates_dormant_infrastructure():
    store = TieredGraphStore(dormancy_seconds=100)
    store.observe("payee-1", "hash-a", confirmed=True, now=0.0)
    store.demote_dormant(now=200.0)
    # Dormant infrastructure reactivates (spec 9.5): reappearance pulls
    # the confirmed history back into the hot path automatically.
    store.observe("payee-1", "hash-b", now=200.0)
    assert store.hot_graph.has_edge("payee-1", "hash-a")
    assert store.hot_graph.edges["payee-1", "hash-a"].get("confirmed") is True


def test_tiered_store_active_cluster_keeps_neighborhood_hot():
    store = TieredGraphStore(dormancy_seconds=100)
    store.observe("hub", "old-node", now=0.0)
    store.observe("hub", "fresh-node", now=150.0)   # hub itself refreshed
    demoted = store.demote_dormant(now=180.0)
    # old-node is stale but its neighbor is active -> retained (spec 7.7).
    assert "old-node" not in demoted


# ---------------------------------------------------------------- centrality

def test_centrality_exact_on_small_graph():
    g = nx.path_graph(9)
    res = chokepoints_with_fallback(nx.relabel_nodes(g, str), top_k=3)
    assert res.method == "betweenness_exact"
    assert res.ranking[0][0] == "4"          # middle of a path = max betweenness


def test_centrality_sampled_on_large_graph():
    g = nx.relabel_nodes(nx.barabasi_albert_graph(800, 3, seed=2), str)
    res = chokepoints_with_fallback(g, budget_seconds=30.0)
    assert res.method in ("betweenness_sampled", "betweenness_exact")
    assert len(res.ranking) == 10


def test_centrality_fallback_is_labeled_never_silent():
    g = nx.relabel_nodes(nx.karate_club_graph(), str)
    res = chokepoints_with_fallback(g, _force_timeout=True)
    assert res.method == "eigenvector_fallback"   # labeled, per 2.5 discipline
    assert res.ranking                            # still a real ranking


# ---------------------------------------------------------------- thermal

def test_thermal_ladder_cascade_lever_before_precision_loss():
    gov = ThermalGovernor()
    p = gov.update(0.75)
    # ELEVATED: Tier 2 still full-precision, invoked more rarely (7.1).
    assert gov.state == ThermalState.ELEVATED
    assert p.tier2_variant == "4bit" and p.escalation_bar_multiplier > 1.0
    p = gov.update(0.90)
    # SEVERE: only now the pre-built 2-bit variant, as last resort.
    assert p.tier2_variant == "2bit"


def test_thermal_degraded_mode_contract_never_silent():
    gov = ThermalGovernor()
    p = gov.update(0.90, cpu_fallback_active=True)   # 10.1 compound scenario
    assert gov.state == ThermalState.CRITICAL_COMPOUND
    assert p.max_tier == 0
    assert p.user_notice is not None and "verify" in p.user_notice.lower()


def test_thermal_hysteresis_prevents_flapping():
    gov = ThermalGovernor()
    gov.update(0.86)                                  # -> SEVERE
    assert gov.state == ThermalState.SEVERE
    gov.update(0.84)                                  # inside hysteresis band
    assert gov.state == ThermalState.SEVERE           # no flap
    gov.update(0.79)                                  # below 0.85 - 0.05
    assert gov.state == ThermalState.ELEVATED         # damped, one rung


def test_thermal_policy_contains_no_detection_threshold():
    # STRICT SUMMARY: device state never changes what counts as true.
    from detection.telemetry.thermal_governor import CascadePolicy
    fields = set(CascadePolicy.__dataclass_fields__)
    assert not any("entail" in f or "confidence" in f or "detection" in f
                   for f in fields)
