"""
Evidence citer -- shared across every detection module.

Spec ref: PDF Section 2.5 / Strict Instruction Summary: "Every flag cites
the exact evidence that produced it -- a transcript span, a permission
name, a header field, an OCR'd region. No unexplained risk scores."

This is intentionally a thin, uniform data contract, not per-module logic:
conversation candidates, permission-graph findings, and OCR regions all
normalize into the same `Citation` shape so the client UI (and the eval
harness) has exactly one rendering path for "why was I shown this",
instead of a different ad-hoc explanation format per module.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class EvidenceKind(str, Enum):
    TRANSCRIPT_SPAN = "transcript_span"
    PERMISSION_NAME = "permission_name"
    HEADER_FIELD = "header_field"
    OCR_REGION = "ocr_region"
    ACOUSTIC_SEGMENT = "acoustic_segment"
    GRAPH_LINK = "graph_link"


@dataclass(frozen=True)
class Citation:
    kind: EvidenceKind
    value: str          # the actual cited text/name/region
    source_locator: str  # turn index, region tag, permission list position, etc.


def cite_transcript_span(span: str, turn_index: int) -> Citation:
    return Citation(kind=EvidenceKind.TRANSCRIPT_SPAN, value=span, source_locator=f"turn={turn_index}")


def cite_permission(permission_name: str, package: str) -> Citation:
    return Citation(kind=EvidenceKind.PERMISSION_NAME, value=permission_name, source_locator=f"package={package}")


def cite_ocr_region(text: str, region_tag: str) -> Citation:
    return Citation(kind=EvidenceKind.OCR_REGION, value=text, source_locator=f"region={region_tag}")


def cite_graph_link(node_a: str, node_b: str, report_count: int) -> Citation:
    return Citation(kind=EvidenceKind.GRAPH_LINK, value=f"{node_a} <-> {node_b}", source_locator=f"corroborating_reports={report_count}")


def render_for_user(citations: list[Citation]) -> str:
    """Plain-language rendering -- what the client UI's warning screen
    actually shows. No jargon, since spec 4/equity_eval.py cares about
    non-technical and non-native-speaker readability."""
    if not citations:
        return "No specific evidence cited."
    lines = []
    for c in citations:
        if c.kind == EvidenceKind.TRANSCRIPT_SPAN:
            lines.append(f'Message said: "{c.value}"')
        elif c.kind == EvidenceKind.PERMISSION_NAME:
            lines.append(f"App permission: {c.value}")
        elif c.kind == EvidenceKind.OCR_REGION:
            lines.append(f'On screen ({c.source_locator.replace("region=", "")}): "{c.value}"')
        elif c.kind == EvidenceKind.ACOUSTIC_SEGMENT:
            lines.append(f"Call audio: {c.value}")
        elif c.kind == EvidenceKind.GRAPH_LINK:
            lines.append(f"Matches a pattern reported by other users: {c.value}")
        else:
            lines.append(c.value)
    return "\n".join(f"- {l}" for l in lines)
