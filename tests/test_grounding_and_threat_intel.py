"""
Tests for grounding/ (NLI gate, confidence gate) and threat-intel/
(campaign graph k-anonymity, predictor centrality/PageRank/embeddings).
"""
import time
import networkx as nx

from detection.conversation.model_cascade import route, TacticCandidate
from grounding.nli_entailment_gate import evaluate_entailment, gate_candidates
from grounding.confidence_gate import apply as apply_confidence_gate, any_surfaced

from campaign_graph import CampaignGraph, K_ANONYMITY_FLOOR, _node_key  # threat-intel/, flat-imported (see conftest.py)
from community_feed import CommunityReport, PatternKind
from campaign_predictor import compute_embeddings, find_closest_cluster, betweenness_chokepoints, personalized_suspicion_pagerank


def test_nli_gate_catches_negation_and_hypothetical_without_swallowing_real_flags():
    negated = TacticCandidate("payment_channel_funneling", ["gift card"], 0.9,
                               "I would never send a gift card to someone I just met.")
    assert evaluate_entailment(negated).survived is False

    hypothetical = TacticCandidate("payment_channel_funneling", ["gift card"], 0.5,
                                    "What if someone asked me to buy a gift card?")
    assert evaluate_entailment(hypothetical).survived is False

    # regression: unrelated negation word elsewhere in the sentence must
    # NOT suppress a genuine flag (proximity-scoped negation check)
    real_flag_text = "I've never felt this way about anyone before. I need you to wire the money today, it's urgent, and please don't tell your family about us yet."
    r = route(real_flag_text)
    survivors, _ = gate_candidates(r.candidates)
    assert any(c.tactic_id == "payment_channel_funneling" for c in survivors)


def test_confidence_gate_end_to_end():
    r = route("send the money now, only accept gift card, do not tell your bank, this is the irs")
    survivors, entailment_results = gate_candidates(r.candidates)
    gated = apply_confidence_gate(entailment_results)
    assert any_surfaced(gated)

    r_benign = route("hey how are you doing today")
    _, er_benign = gate_candidates(r_benign.candidates)
    assert not any_surfaced(apply_confidence_gate(er_benign))


def test_campaign_graph_k_anonymity_gate():
    g = CampaignGraph()
    phone_key = _node_key(PatternKind.PHONE_NUMBER, "+15550001111")
    payee_key = _node_key(PatternKind.PAYEE_ACCOUNT, "acct_scammer_882")

    for i in range(K_ANONYMITY_FLOOR - 1):
        g.record_incident([
            CommunityReport(PatternKind.PHONE_NUMBER, "+15550001111", "irs_impersonation", time.time(), f"attest_{i}"),
            CommunityReport(PatternKind.PAYEE_ACCOUNT, "acct_scammer_882", "irs_impersonation", time.time(), f"attest_{i}"),
        ])
    assert g.is_link_exposable(phone_key, payee_key) is False
    assert g.k_anonymized_view().number_of_edges() == 0

    g.record_incident([
        CommunityReport(PatternKind.PHONE_NUMBER, "+15550001111", "irs_impersonation", time.time(), "attest_final"),
        CommunityReport(PatternKind.PAYEE_ACCOUNT, "acct_scammer_882", "irs_impersonation", time.time(), "attest_final"),
    ])
    assert g.is_link_exposable(phone_key, payee_key) is True
    assert g.k_anonymized_view().number_of_edges() == 1


def test_campaign_graph_entity_type_decay():
    g = CampaignGraph()
    now = time.time()
    phone_key = _node_key(PatternKind.PHONE_NUMBER, "+15550001111")
    payee_key = _node_key(PatternKind.PAYEE_ACCOUNT, "acct_x")
    g.record_incident([
        CommunityReport(PatternKind.PHONE_NUMBER, "+15550001111", "romance_scam", now, "a"),
        CommunityReport(PatternKind.PAYEE_ACCOUNT, "acct_x", "romance_scam", now, "a"),
    ])
    g.graph.nodes[phone_key]["last_seen"] = now - 300 * 86400
    assert g.node_live_risk_active(phone_key, now=now) is False
    assert g.node_live_risk_active(payee_key, now=now) is True  # persistent, never decays
    assert g.historical_record_preserved(phone_key) is True     # history never erased


def test_campaign_predictor_finds_real_bridge_via_betweenness():
    g = nx.Graph()
    cluster_a = [f"payee_a{i}" for i in range(5)]
    cluster_b = [f"payee_b{i}" for i in range(5)]
    g.add_edges_from([(cluster_a[i], cluster_a[j]) for i in range(5) for j in range(i + 1, 5)])
    g.add_edges_from([(cluster_b[i], cluster_b[j]) for i in range(5) for j in range(i + 1, 5)])
    bridge = "cashout_hub"
    g.add_edge(bridge, cluster_a[0])
    g.add_edge(bridge, cluster_b[0])

    chokepoints = betweenness_chokepoints(g, top_k=3)
    top_score = chokepoints[0][1]
    top_tier = {n for n, s in chokepoints if s == top_score}
    assert bridge in top_tier

    pr = personalized_suspicion_pagerank(g, known_bad_nodes=[cluster_a[0]], top_k=5)
    assert pr[0][1] > 0

    embeddings = compute_embeddings(g, seed=7)
    assert len(embeddings) == g.number_of_nodes()
