/**
 * Vite config for the TrustTrace researcher dashboard.
 *
 * Spec ref: PDF Section 2.11 (client-rendered dashboard) + the single
 * FastAPI backend (Target Environment). The dev proxy forwards the
 * campaign-graph API to that backend so the SPA can fetch /v1/* during
 * local development without CORS configuration.
 */
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Forward the k-anonymized campaign-graph endpoint (and any other
      // /v1 routes) to the FastAPI service. Adjust the target if the
      // backend runs elsewhere.
      "/v1": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
