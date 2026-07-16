"""
Pydantic request/response models.

Spec ref: PDF Section 7.2: "Auto-generated TypeScript interfaces from
FastAPI's Pydantic models" -- these schemas are the single source of
truth the dashboard's TypeScript types (spec 7.2) would be generated from
(e.g. via `datamodel-code-generator` or FastAPI's own OpenAPI export +
`openapi-typescript`).

NOT execution-verified in this sandbox -- see backend/config.py's note.
"""
from __future__ import annotations
from pydantic import BaseModel, Field


class AnalyzeTranscriptRequest(BaseModel):
    session_id: str
    sender: str
    text: str = Field(..., max_length=8000)


class GatedFlagResponse(BaseModel):
    tactic_id: str
    verdict: str
    confidence: float
    explanation: str


class AnalyzeTranscriptResponse(BaseModel):
    tier_reached: int
    flags: list[GatedFlagResponse]
    any_surfaced: bool


class ExplainMoreRequest(BaseModel):
    """Spec 5: opt-in per use, never automatic. This endpoint is the ONLY
    code path in the backend that may call an external cloud LLM
    provider -- see llm_client.py."""
    session_id: str
    transcript_excerpt: str = Field(..., max_length=4000)


class ExplainMoreResponse(BaseModel):
    explanation: str
    provider_used: str


class CampaignGraphNode(BaseModel):
    node_key: str
    kind: str


class CampaignGraphEdge(BaseModel):
    node_a: str
    node_b: str
    corroborating_report_count: int


class CampaignGraphView(BaseModel):
    """Only ever built from CampaignGraph.k_anonymized_view() --
    see threat-intel/campaign_graph.py. No field here can carry a raw
    individual report or transcript, by construction of the upstream type."""
    nodes: list[CampaignGraphNode]
    edges: list[CampaignGraphEdge]
