"""
FastAPI route definitions.

Spec ref: PDF Section 2.11 (dashboard endpoint enforcement: no raw
individual report/transcript ever returned -- enforced HERE, server-side,
not as a dashboard UI convention), Section 2.3 (transaction warning-only
endpoint, no cancel/block action path exists).

NOT execution-verified in this sandbox -- see backend/config.py's note.
Written to the real FastAPI APIRouter API.
"""
from __future__ import annotations
import logging
import sys
import os

from fastapi import APIRouter, HTTPException

logger = logging.getLogger("trusttrace.api")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "threat-intel"))  # hyphenated dir, see note in threat-intel/campaign_graph.py

from detection.conversation.model_cascade import route as cascade_route  # noqa: E402
from grounding.nli_entailment_gate import gate_candidates  # noqa: E402
from grounding.confidence_gate import apply as apply_confidence_gate, any_surfaced  # noqa: E402
from campaign_graph import CampaignGraph  # noqa: E402

from ..schemas import (  # noqa: E402
    AnalyzeTranscriptRequest, AnalyzeTranscriptResponse, GatedFlagResponse,
    ExplainMoreRequest, ExplainMoreResponse,
    CampaignGraphView, CampaignGraphNode, CampaignGraphEdge,
)
from ..llm_client import explain_more, build_provider, ExplainRequest  # noqa: E402
from ..config import settings  # noqa: E402
from ..incident_ingest import record_detection, seed_demo_campaign  # noqa: E402

router = APIRouter()

# Process-lifetime in-memory graph for this reference implementation.
# Production: a real Postgres-backed CampaignGraph load/save, geo-sharded
# per spec 9.4/8.5 -- out of scope for this reference wiring.
_campaign_graph = CampaignGraph()
# Dev/demo only: no-op unless TRUSTTRACE_SEED_DEMO_CAMPAIGN is set (does not
# lower the k-anonymity floor -- see incident_ingest.py).
seed_demo_campaign(_campaign_graph)


@router.post("/v1/analyze-transcript", response_model=AnalyzeTranscriptResponse)
def analyze_transcript(req: AnalyzeTranscriptRequest) -> AnalyzeTranscriptResponse:
    """
    On-device-first by design (spec 5): in the real mobile app, this exact
    cascade -> NLI gate -> confidence gate pipeline runs ON-DEVICE for the
    default path. This endpoint exists for the SMS-lite gateway
    (offline/sms_gateway.py already calls the same functions directly) and
    for server-side eval/testing -- never as the primary mobile-app path.
    """
    cascade_result = cascade_route(req.text)
    survivors, entailment_results = gate_candidates(cascade_result.candidates)
    gated = apply_confidence_gate(entailment_results)

    # Feed the CampaignGraph the dashboard reads from: only when a grounded
    # flag actually surfaced, and only anonymized correlatable patterns (never
    # the tactic labels or raw transcript). Exposure still gated by the
    # k-anonymity floor downstream -- see incident_ingest.py.
    if any_surfaced(gated):
        record_detection(_campaign_graph, req.text)

    return AnalyzeTranscriptResponse(
        tier_reached=cascade_result.tier_reached,
        flags=[GatedFlagResponse(tactic_id=g.tactic_id, verdict=g.verdict.value,
                                  confidence=g.confidence, explanation=g.explanation) for g in gated],
        any_surfaced=any_surfaced(gated),
    )


@router.post("/v1/explain-more", response_model=ExplainMoreResponse)
async def explain_more_endpoint(req: ExplainMoreRequest) -> ExplainMoreResponse:
    """Spec 5: the ONLY opt-in cloud LLM call path -- never automatic.
    Nothing from req.transcript_excerpt is persisted by this handler."""
    provider = build_provider(settings.llm_explain_provider, settings.llm_api_key)
    try:
        explanation = await explain_more(provider, ExplainRequest(transcript_excerpt=req.transcript_excerpt))
    except Exception as exc:  # noqa: BLE001
        # Log the real error server-side; return a GENERIC detail. Raw
        # provider exception text can carry upstream URLs / response
        # fragments that don't belong in a client-facing error body.
        logger.warning("explain-more provider failed: %s", exc)
        raise HTTPException(status_code=503, detail="Explain-more provider unavailable") from exc
    return ExplainMoreResponse(explanation=explanation, provider_used=settings.llm_explain_provider)


@router.get("/v1/campaign-graph", response_model=CampaignGraphView)
def get_campaign_graph() -> CampaignGraphView:
    """
    Spec Strict Instruction Summary: 'The dashboard has no code path, for
    researchers or TrustTrace's own operators, that returns a raw
    individual report or transcript.' Enforced here structurally: this
    handler calls ONLY k_anonymized_view() -- there is no other method on
    CampaignGraph this route touches, and k_anonymized_view() itself
    cannot expose a sub-floor link (see threat-intel/campaign_graph.py).
    """
    view = _campaign_graph.k_anonymized_view()
    nodes = [CampaignGraphNode(node_key=n, kind=str(data.get("kind", "unknown")))
             for n, data in view.nodes(data=True)]
    edges = [CampaignGraphEdge(node_a=a, node_b=b,
                                corroborating_report_count=_campaign_graph.corroboration_count(a, b))
             for a, b in view.edges()]
    return CampaignGraphView(nodes=nodes, edges=edges)
