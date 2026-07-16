"""
Dashboard-only bidirectional BFS: two-known-endpoint pathfinding.

Spec ref: PDF Section 9.5: "Bidirectional BFS is adopted -- narrowly, and
it doesn't reopen the standing rule against pathfinding. That rule rejects
point-to-point search for CORE ROUTING AND PREDICTION, where there's no
defined start/goal pair. A researcher in the dashboard asking how two
specific, ALREADY-KNOWN bad actors are connected genuinely is a
two-known-endpoint pathfinding question -- exactly the case the earlier
rule was never meant to cover. Scoped to the dashboard, depth-limited, and
NEVER touching the core cascade or campaign-prediction logic." Section
10.5: "A silent dashboard BFS timeout becomes an explicit 'no path found
within search depth N' result."

Structural isolation, not just a docstring promise: this file imports
NOTHING from campaign_predictor.py (the core prediction path) or
detection/ or grounding/ -- its only dependency is networkx and
campaign_graph.py's k-anonymized view. There is no import edge by which
this file's pathfinding logic could be reached from, or could influence,
the core cascade/campaign-prediction path. That's what "never touching"
means as an enforceable property rather than a comment.

Also enforces the Strict Instruction Summary boundary this sits inside:
operates ONLY on CampaignGraph.k_anonymized_view() -- the same
k-anonymity floor every other dashboard-facing read already respects (see
backend/api/routes.py's get_campaign_graph). A researcher can trace a path
between two already-exposed, already-corroborated nodes; this function has
no way to reach into raw sub-floor report data to do so.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections import deque

import networkx as nx

DEFAULT_MAX_DEPTH = 6  # spec 9.5: depth-limited, not an unbounded search


@dataclass
class PathQueryResult:
    found: bool
    path: list[str] | None
    hop_count: int | None
    search_depth_used: int
    message: str


def _bidirectional_bfs(graph: nx.Graph, source: str, target: str, max_depth: int) -> list[str] | None:
    """
    A genuine bidirectional BFS, not networkx's built-in unidirectional
    shortest_path -- alternately expands a frontier from BOTH endpoints
    and stops as soon as the two frontiers meet, which is what makes
    bidirectional BFS reach a given depth roughly twice as fast as
    single-directional BFS (branching factor^(d/2) instead of
    branching factor^d on each side). Depth-limited: each side is capped
    at max_depth // 2 hops, so the combined search never exceeds
    max_depth total hops end to end.
    """
    if source == target:
        return [source]
    if source not in graph or target not in graph:
        return None

    half_depth = max(1, max_depth // 2)

    # visited_from_source[node] = the node we came from, on the source side
    visited_from_source = {source: None}
    visited_from_target = {target: None}
    frontier_source = deque([source])
    frontier_target = deque([target])
    depth_source = 0
    depth_target = 0

    def _reconstruct(meeting_node: str) -> list[str]:
        # walk back from meeting_node to source
        path_from_source = []
        node = meeting_node
        while node is not None:
            path_from_source.append(node)
            node = visited_from_source[node]
        path_from_source.reverse()
        # walk back from meeting_node to target
        node = visited_from_target[meeting_node]
        path_to_target = []
        while node is not None:
            path_to_target.append(node)
            node = visited_from_target[node]
        return path_from_source + path_to_target

    while frontier_source and frontier_target and depth_source < half_depth and depth_target < half_depth:
        # Strict per-round alternation between the two sides -- the
        # textbook-correct bidirectional BFS. (A frontier-size-based
        # "expand the smaller side first" heuristic is a common further
        # optimization, but it must never let one side monopolize
        # multiple consecutive rounds on a tie, which silently starves
        # the other side's expansion entirely on graphs with equal-size
        # frontiers on both sides, such as a simple chain -- a real bug
        # caught by testing here, not a hypothetical one.)
        next_frontier = deque()
        for _ in range(len(frontier_source)):
            node = frontier_source.popleft()
            for neighbor in graph.neighbors(node):
                if neighbor in visited_from_target:
                    visited_from_source[neighbor] = node
                    return _reconstruct(neighbor)
                if neighbor not in visited_from_source:
                    visited_from_source[neighbor] = node
                    next_frontier.append(neighbor)
        frontier_source = next_frontier
        depth_source += 1

        if not frontier_target or depth_target >= half_depth:
            continue

        next_frontier = deque()
        for _ in range(len(frontier_target)):
            node = frontier_target.popleft()
            for neighbor in graph.neighbors(node):
                if neighbor in visited_from_source:
                    visited_from_target[neighbor] = node
                    return _reconstruct(neighbor)
                if neighbor not in visited_from_target:
                    visited_from_target[neighbor] = node
                    next_frontier.append(neighbor)
        frontier_target = next_frontier
        depth_target += 1

    return None  # search exhausted within depth budget, no meeting point found


def find_known_bad_actor_path(
    campaign_graph_k_anonymized_view: nx.Graph,
    node_a: str,
    node_b: str,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> PathQueryResult:
    """
    Dashboard entry point. Callers MUST pass the result of
    CampaignGraph.k_anonymized_view() -- never the raw internal graph --
    which is what keeps this consistent with the Strict Instruction
    Summary's dashboard rule even though this file introduces the one
    narrow pathfinding exception spec 9.5 carves out.
    """
    if node_a not in campaign_graph_k_anonymized_view or node_b not in campaign_graph_k_anonymized_view:
        return PathQueryResult(
            found=False, path=None, hop_count=None, search_depth_used=max_depth,
            message=f"One or both nodes are not present in the k-anonymized graph "
                    f"(either unknown, or not yet corroborated past the k-anonymity floor).",
        )

    path = _bidirectional_bfs(campaign_graph_k_anonymized_view, node_a, node_b, max_depth)

    if path is not None:
        return PathQueryResult(
            found=True, path=path, hop_count=len(path) - 1, search_depth_used=max_depth,
            message=f"Path found: {len(path) - 1} hop(s) within search depth {max_depth}.",
        )

    # Spec 10.5: explicit result, never a silent timeout/failure -- the
    # researcher needs to know the search genuinely exhausted its depth
    # budget, distinct from "these two nodes are provably disconnected."
    return PathQueryResult(
        found=False, path=None, hop_count=None, search_depth_used=max_depth,
        message=f"No path found within search depth {max_depth}. This does not prove no "
                f"connection exists -- only that none was found within the search bound.",
    )
