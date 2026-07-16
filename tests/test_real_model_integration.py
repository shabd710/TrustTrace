"""
Tests for the real-model integration seams (Linux+GPU swap-ins).

Verifies the FALLBACK contract: when a heavy dep (llama_cpp, faiss,
torch_geometric, transformers, pysqlcipher3) is absent -- as in CI and
this sandbox -- each seam degrades to the tested pure-Python path with
identical interfaces, never crashing the cascade/gate/index. On a box
WITH the deps, these same seams activate the real models (see
docs/REAL_MODELS_SETUP.md).
"""
from __future__ import annotations

import networkx as nx
import numpy as np

from detection.conversation.llm_runtime import refine_candidates_with_llm
from detection.conversation.model_cascade import route
from grounding.nli_cross_encoder import evaluate_entailment_nli
from campaign_predictor_sage import compute_embeddings_or_fallback
from ann_faiss import build_faiss_or_fallback
from campaign_predictor import compute_embeddings


def test_llm_runtime_fallback_returns_none_without_weights():
    assert refine_candidates_with_llm("hi", ["urgency_injection"]) is None
    assert refine_candidates_with_llm("hi", []) is None


def test_cascade_still_works_with_llm_hook_present():
    r = route("This is your bank. Act now and buy a gift card, don't tell your family.")
    tactics = {c.tactic_id for c in r.candidates}
    assert "payment_channel_funneling" in tactics
    assert r.tier_reached >= 1


def test_faiss_fallback_matches_hnsw_interface():
    emb = {f"n{i}": np.random.default_rng(i).random(16) for i in range(40)}
    idx = build_faiss_or_fallback(emb)
    res = idx.query(emb["n5"], top_k=3)
    assert len(res) == 3
    assert res[0].node_id == "n5"
    assert res[0].distance < 1e-6
    assert all(hasattr(m, "node_id") and hasattr(m, "distance") for m in res)


def test_sage_fallback_matches_base_embedding_shape():
    g = nx.relabel_nodes(nx.karate_club_graph(), str)
    sage = compute_embeddings_or_fallback(g)
    base = compute_embeddings(g)
    assert set(sage.keys()) == set(base.keys())
    for k in base:
        assert np.allclose(sage[k], base[k])


def test_nli_cross_encoder_fallback_returns_none():
    assert evaluate_entailment_nli("premise text", "hypothesis text") is None


def test_sqlcipher_store_opens_and_flags_encryption_honestly(tmp_path):
    from security.sqlcipher_store import open_encrypted_store
    db = str(tmp_path / "t.db")
    store = open_encrypted_store(db)
    assert store.encrypted is False
    store.connection.execute("INSERT INTO _trusttrace_meta VALUES ('k','v')")
    store.connection.commit()
    row = store.connection.execute("SELECT v FROM _trusttrace_meta WHERE k='k'").fetchone()
    assert row[0] == "v"
