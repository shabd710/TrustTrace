/**
 * Vite SPA entry point for the researcher dashboard.
 *
 * Spec ref: PDF Section 2.11 — client-rendered React app querying only
 * the k-anonymized aggregate graph endpoint. This mounts
 * CampaignGraphView (from the existing App.js, via AppBridge) into
 * #root, injecting the real network fetch as `fetchImpl`.
 *
 * The dev proxy (see vite.config.js) forwards /v1/* to the FastAPI
 * backend on :8000, so `fetch("/v1/campaign-graph")` reaches
 * backend/api/routes.py::get_campaign_graph in local dev with no CORS
 * setup. In production, serve this build behind the same origin as the
 * API, or set an explicit base URL.
 */
import React from "react";
import { createRoot } from "react-dom/client";
import CampaignGraphView from "./AppBridge.jsx";

const rootEl = document.getElementById("root");
createRoot(rootEl).render(
  React.createElement(CampaignGraphView, {
    // Real network fetch — the component is otherwise fetch-agnostic,
    // which is exactly what made it unit-testable with a stub earlier.
    fetchImpl: (path) => fetch(path),
  })
);
