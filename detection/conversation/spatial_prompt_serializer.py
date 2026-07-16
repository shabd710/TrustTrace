"""
OCR bounding-box -> structured prompt serializer.

Spec ref: PDF Section 3.3, corrected by 7.5 (percentage-based coordinates,
resolution-independent, replacing raw pixel boxes) and 10.1 (OCR confidence
gates downstream trust; low-confidence regions are marked uncertain, never
silently healed into confident text).

Real, running logic: this file has NO dependency on VNRecognizeTextRequest
itself (that's iOS-only, Section 2.8's job, native Swift) -- it only
consumes whatever bounding-box + text + confidence tuples an OCR engine
produces, in a plain Python-representable shape, and does the actual
region-bucketing + serialization. That means this half of the pipeline is
real and testable here; only the OCR capture step is native-only.
"""
from __future__ import annotations
from dataclasses import dataclass

# 3x3 region grid -- coarse enough to be cheap and robust to OCR box jitter,
# fine enough to distinguish "an amount in the confirmation field" from
# "an amount in a promotional banner" (the false-positive source spec 3.3
# names explicitly).
_COL_LABELS = ("left", "center", "right")
_ROW_LABELS = ("top", "middle", "bottom")

OCR_LOW_CONFIDENCE_THRESHOLD = 0.55


@dataclass
class OcrBox:
    text: str
    confidence: float  # 0..1, as VNRecognizeTextRequest actually reports
    # Percentage-based, resolution-independent per spec 7.5 -- NOT raw
    # pixels, so the same serializer output is valid across every device's
    # screen resolution without re-tuning region thresholds per device.
    x_pct: float  # 0..100, left edge
    y_pct: float  # 0..100, top edge
    w_pct: float
    h_pct: float


def _region_for(box: OcrBox) -> str:
    cx = box.x_pct + box.w_pct / 2
    cy = box.y_pct + box.h_pct / 2
    col = _COL_LABELS[min(2, int(cx // (100 / 3)))]
    row = _ROW_LABELS[min(2, int(cy // (100 / 3)))]
    return f"{row}-{col}"


def serialize(boxes: list[OcrBox]) -> str:
    """
    Produces the compact, region-tagged text block fed directly into the
    Tier 2 prompt (spec 3.3). Token-healing (spec 9.3) for adjacent-region
    mid-word concatenation is intentionally NOT re-implemented here -- it
    operates on raw OCR engine output before boxes are finalized, upstream
    of this function's input contract.
    """
    if not boxes:
        return "[no on-screen text detected]"

    by_region: dict[str, list[OcrBox]] = {}
    for box in boxes:
        by_region.setdefault(_region_for(box), []).append(box)

    lines = []
    # Deterministic region ordering (reading order: top-to-bottom,
    # left-to-right) so the same screen always serializes identically --
    # matters for the NLI gate's reproducibility requirement (spec 7.3).
    ordered_regions = [f"{r}-{c}" for r in _ROW_LABELS for c in _COL_LABELS]
    for region in ordered_regions:
        region_boxes = by_region.get(region)
        if not region_boxes:
            continue
        region_boxes.sort(key=lambda b: (b.y_pct, b.x_pct))
        parts = []
        for b in region_boxes:
            if b.confidence < OCR_LOW_CONFIDENCE_THRESHOLD:
                # Spec 10.1: low-confidence OCR is uncertain evidence, cited
                # as such -- never silently presented as confident text.
                parts.append(f"{b.text} [low-confidence]")
            else:
                parts.append(b.text)
        lines.append(f"[{region}] " + " | ".join(parts))
    return "\n".join(lines)
