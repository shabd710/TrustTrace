/**
 * Researcher dashboard -- React, k-anonymized-aggregate-only.
 *
 * Spec ref: PDF Section 2.11 / Strict Instruction Summary: "The dashboard
 * has no code path, for researchers or TrustTrace's own operators, that
 * returns a raw individual report or transcript." Section 9.5's narrow
 * bidirectional-BFS carve-out: a researcher asking how two ALREADY-KNOWN
 * bad actors are connected is a genuine two-known-endpoint pathfinding
 * question, scoped to this dashboard only, depth-limited, never touching
 * the core cascade/campaign-prediction path.
 *
 * Enforcement note: this component only ever calls GET /v1/campaign-graph
 * (backend/api/routes.py's get_campaign_graph, which itself only reads
 * CampaignGraph.k_anonymized_view() -- see threat-intel/campaign_graph.py).
 * There is no fetch call anywhere in this file to any endpoint that could
 * return raw report data, because no such endpoint exists in this codebase
 * for it to call.
 *
 * Written as plain React.createElement (no JSX/build step) so it is
 * directly executable/testable via Node + react-dom/server in this
 * environment -- see the render smoke-test run alongside this file.
 */
import React from "react";
const { useState, useEffect } = React;
const e = React.createElement;

function CampaignGraphView({ fetchImpl }) {
  const [graph, setGraph] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchImpl("/v1/campaign-graph")
      .then((res) => res.json())
      .then(setGraph)
      .catch((err) => setError(String(err)));
  }, [fetchImpl]);

  if (error) return e("div", { className: "error" }, `Failed to load campaign graph: ${error}`);
  if (!graph) return e("div", { className: "loading" }, "Loading k-anonymized campaign graph...");

  return e(
    "div",
    { className: "campaign-graph-view" },
    e("h2", null, "Campaign Correlation Graph (k-anonymized aggregate only)"),
    e(
      "p",
      { className: "disclosure" },
      "Every link shown here has been corroborated by independent reports " +
        "past the k-anonymity floor. No individual report or transcript is " +
        "ever returned by this view."
    ),
    e(
      "ul",
      { className: "node-list" },
      graph.nodes.map((n) => e("li", { key: n.node_key }, `${n.kind}: ${n.node_key}`))
    ),
    e(
      "ul",
      { className: "edge-list" },
      graph.edges.map((edge) =>
        e(
          "li",
          { key: `${edge.node_a}--${edge.node_b}` },
          `${edge.node_a} <-> ${edge.node_b} (${edge.corroborating_report_count} corroborating reports)`
        )
      )
    )
  );
}

export { CampaignGraphView };
