"""
Tests for threat-intel/dashboard_path_query.py -- the spec 9.5
bidirectional-BFS carve-out, scoped to the dashboard only.
"""
import random
import networkx as nx

from dashboard_path_query import find_known_bad_actor_path


def _chain_graph():
    g = nx.Graph()
    chain = ["a", "b", "c", "d", "e", "f", "g"]
    g.add_edges_from(zip(chain, chain[1:]))
    return g, chain


def test_finds_shortest_path_within_budget():
    g, chain = _chain_graph()
    r = find_known_bad_actor_path(g, "a", "d", max_depth=6)
    assert r.found is True
    assert r.path == ["a", "b", "c", "d"]
    assert r.hop_count == 3


def test_finds_path_exactly_at_depth_limit():
    g, chain = _chain_graph()
    r = find_known_bad_actor_path(g, "a", "g", max_depth=6)
    assert r.found is True
    assert r.hop_count == 6
    assert r.path == chain


def test_explicit_message_when_beyond_depth_budget():
    g, _ = _chain_graph()
    r = find_known_bad_actor_path(g, "a", "g", max_depth=2)
    assert r.found is False
    assert "within search depth 2" in r.message


def test_unknown_node_returns_explicit_result_not_crash():
    g, _ = _chain_graph()
    r = find_known_bad_actor_path(g, "a", "totally_unknown_node", max_depth=6)
    assert r.found is False
    assert "not present" in r.message


def test_same_node_trivial_path():
    g, _ = _chain_graph()
    r = find_known_bad_actor_path(g, "a", "a", max_depth=6)
    assert r.path == ["a"]
    assert r.hop_count == 0


def test_matches_networkx_shortest_path_on_random_graphs():
    random.seed(3)
    dense = nx.gnm_random_graph(60, 150, seed=3)
    dense = nx.relabel_nodes(dense, {i: f"node_{i}" for i in dense.nodes()})
    checked = 0
    for _ in range(30):
        a, b = random.sample(list(dense.nodes()), 2)
        if nx.has_path(dense, a, b):
            true_len = nx.shortest_path_length(dense, a, b)
            if true_len <= 20:
                result = find_known_bad_actor_path(dense, a, b, max_depth=20)
                assert result.found
                assert result.hop_count == true_len
                checked += 1
    assert checked > 10  # sanity: the random seed actually exercised enough cases


def test_reconstructed_paths_use_real_edges():
    random.seed(3)
    dense = nx.gnm_random_graph(60, 150, seed=3)
    dense = nx.relabel_nodes(dense, {i: f"node_{i}" for i in dense.nodes()})
    for _ in range(10):
        a, b = random.sample(list(dense.nodes()), 2)
        result = find_known_bad_actor_path(dense, a, b, max_depth=20)
        if result.found:
            for u, v in zip(result.path, result.path[1:]):
                assert dense.has_edge(u, v)


def test_structurally_isolated_from_core_prediction_path():
    import ast
    import pathlib
    _repo_root = pathlib.Path(__file__).resolve().parent.parent
    src = (_repo_root / "threat-intel" / "dashboard_path_query.py").read_text()
    tree = ast.parse(src)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [n.name for n in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module)
    assert not any("campaign_predictor" in (n or "") for n in imported)
    assert not any("detection" in (n or "") for n in imported)
    assert not any("grounding" in (n or "") for n in imported)
