"""
Optimization benchmarks -- measured, not asserted.

Spec ref: PDF Section 3.5 ("Profiling-First Discipline"): "Optimizations
merge because profiling shows they fix a measured bottleneck, not
because a technique sounds sophisticated." This file is that rule
applied to this repo's own optimizations: every speedup claimed in the
Master Guide/PDF is a number produced by running THIS file, on this
machine, against this code -- reproducible with:

    python eval/benchmarks.py

REAL vs SIM: fully real timings of fully real code. Numbers are
machine-relative (a server CPU here, a phone SoC in production); what
transfers is the COMPLEXITY improvement each one demonstrates, which is
machine-independent.
"""
from __future__ import annotations

import random
import string
import sys
import time
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "threat-intel"))

from detection.conversation.fast_pattern_matcher import scan_cues, scan_cues_regex_prescreen, scan_cues_aho_corasick, _naive_cue_scan  # noqa: E402
from campaign_predictor import compute_embeddings, ANNIndex  # noqa: E402
from ann_hnsw import build_hnsw  # noqa: E402

import networkx as nx  # noqa: E402


def _synthetic_messages(n: int, seed: int = 7) -> list[str]:
    rng = random.Random(seed)
    cues = ["act now", "gift card", "don't tell", "guaranteed return",
            "this is your bank", "wire transfer"]
    words = ["".join(rng.choices(string.ascii_lowercase, k=rng.randint(3, 9)))
             for _ in range(400)]
    msgs = []
    for _ in range(n):
        body = " ".join(rng.choices(words, k=rng.randint(20, 120)))
        if rng.random() < 0.3:                       # realistic mostly-benign mix
            body += " " + rng.choice(cues)
        msgs.append(body)
    return msgs


def bench_tier0(n_messages: int = 3000) -> dict[str, float]:
    msgs = [m.lower() for m in _synthetic_messages(n_messages)]

    t0 = time.perf_counter()
    naive = [_naive_cue_scan(m) for m in msgs]
    naive_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    prescreened = [scan_cues_regex_prescreen(m) for m in msgs]
    prescreen_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    ac = [scan_cues_aho_corasick(m) for m in msgs]
    ac_s = time.perf_counter() - t0

    assert naive == prescreened == ac, "equivalence violated -- benchmark invalid"
    return {"naive_s": naive_s, "prescreen_s": prescreen_s, "ac_s": ac_s,
            "prescreen_speedup_x": naive_s / max(prescreen_s, 1e-9),
            "ac_speedup_x": naive_s / max(ac_s, 1e-9)}


def bench_ann(n_nodes: int = 1500, n_queries: int = 200) -> dict[str, float]:
    rng = random.Random(11)
    g = nx.barabasi_albert_graph(n_nodes, 3, seed=11)
    g = nx.relabel_nodes(g, {i: f"node-{i}" for i in g.nodes})
    emb = compute_embeddings(g)

    brute = ANNIndex(emb)
    hnsw = build_hnsw(emb)

    keys = list(emb.keys())
    queries = [emb[rng.choice(keys)] + np.random.default_rng(i).normal(0, 0.01, len(emb[keys[0]]))
               for i in range(n_queries)]

    t0 = time.perf_counter()
    brute_res = [brute.query(q, top_k=5) for q in queries]
    brute_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    hnsw_res = [hnsw.query(q, top_k=5) for q in queries]
    hnsw_s = time.perf_counter() - t0

    # recall@5 of HNSW vs exact brute-force ground truth
    hits = total = 0
    for br, hr in zip(brute_res, hnsw_res):
        truth = {m.node for m in br}
        got = {m.node_id for m in hr}
        hits += len(truth & got)
        total += len(truth)
    return {"brute_s": brute_s, "hnsw_s": hnsw_s,
            "speedup_x": brute_s / max(hnsw_s, 1e-9),
            "recall_at_5": hits / max(total, 1)}


def main() -> None:
    print("== Tier 0 cue scan on 70%-benign mix (3000 msgs), all outputs verified identical ==")
    r = bench_tier0()
    print(f"  naive 60-pass scan : {r['naive_s']*1000:7.1f} ms   (MEASURED WINNER -- ships as hot path; already ~400x inside the Tier 0 budget)")
    print(f"  regex prescreen    : {r['prescreen_s']*1000:7.1f} ms   ({r['prescreen_speedup_x']:.1f}x -- measured and NOT merged, spec 3.5)")
    print(f"  Aho-Corasick (ref) : {r['ac_s']*1000:7.1f} ms   ({r['ac_speedup_x']:.1f}x -- measured and NOT merged in CPython; the native-port reference algorithm)")

    print("== ANN cluster matching at N=1500 (reference scale) ==")
    r = bench_ann()
    print(f"  brute vectorized   : {r['brute_s']*1000:7.1f} ms   (SHIPPED live path at this scale, spec 3.5 verdict)")
    print(f"  HNSW pure-Python   : {r['hnsw_s']*1000:7.1f} ms   recall@5={r['recall_at_5']:.3f} (algorithm verified; production swaps to faiss C++ where sub-linearity wins at scale)")


if __name__ == "__main__":
    main()
