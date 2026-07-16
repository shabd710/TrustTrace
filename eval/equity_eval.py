"""
Equity-sliced evaluation.

Spec ref: PDF Section 4: "precision/recall broken out by age bracket,
language, and (for voice detection) accent/language of speaker, reported
alongside the aggregate." Section 7.7/8.5: >5% regression on ANY slice is
release-blocking, same weight as battery/latency gates. Section 10.4:
canary sampling must be stratified (federated/model_distribution.py) so
this exact metric doesn't get computed against zero representation of a
subgroup.

Real, running logic: computes real per-slice precision/recall against the
SAME corpus + pipeline evaluate.py uses, just grouped by
LabeledExample.age_bracket / .language instead of aggregated.
"""
from __future__ import annotations
from dataclasses import dataclass

from eval.evaluate import predict_is_manipulation, EvalMetrics
from eval.ground_truth.manipulation_corpus import MANIPULATION_CORPUS, LabeledExample

EQUITY_REGRESSION_THRESHOLD = 0.05  # spec 7.7: same release-blocking weight as battery/latency gates


@dataclass
class SliceResult:
    slice_name: str
    slice_value: str
    metrics: EvalMetrics
    example_count: int


def _metrics_for(examples: list[LabeledExample]) -> EvalMetrics:
    tp = fp = fn = tn = 0
    for ex in examples:
        predicted = predict_is_manipulation(ex.text)
        if predicted and ex.is_manipulation:
            tp += 1
        elif predicted and not ex.is_manipulation:
            fp += 1
        elif not predicted and ex.is_manipulation:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return EvalMetrics(precision, recall, f1, tp, fp, fn, tn)


def evaluate_by_slice(slice_attr: str, corpus: list[LabeledExample] | None = None) -> list[SliceResult]:
    """slice_attr: 'age_bracket' or 'language' -- matches LabeledExample's
    fields exactly, so this function works unchanged for any equity
    dimension the corpus carries."""
    corpus = corpus if corpus is not None else [e for e in MANIPULATION_CORPUS if "adversarial" not in e.note]
    by_slice: dict[str, list[LabeledExample]] = {}
    for ex in corpus:
        by_slice.setdefault(getattr(ex, slice_attr), []).append(ex)

    return [
        SliceResult(slice_name=slice_attr, slice_value=value, metrics=_metrics_for(examples), example_count=len(examples))
        for value, examples in by_slice.items()
    ]


def check_for_regression(baseline: list[SliceResult], candidate: list[SliceResult]) -> list[str]:
    """
    Spec 7.7/8.5: broadened equity CI gate -- >5% regression on ANY slice
    fails the build, release-blocking weight equal to battery/latency
    gates. Compares recall specifically (the metric spec 4 emphasizes for
    equity: missing a scam targeting a vulnerable group is the harm mode
    of concern, not a precision tradeoff).
    """
    baseline_by_value = {r.slice_value: r for r in baseline}
    violations = []
    for c in candidate:
        b = baseline_by_value.get(c.slice_value)
        if b is None or b.metrics.recall <= 0:
            continue
        regression = (b.metrics.recall - c.metrics.recall) / b.metrics.recall
        if regression > EQUITY_REGRESSION_THRESHOLD:
            violations.append(
                f"Slice '{c.slice_name}={c.slice_value}' recall regressed {regression:.1%} "
                f"({b.metrics.recall:.2f} -> {c.metrics.recall:.2f}), exceeds {EQUITY_REGRESSION_THRESHOLD:.0%} threshold."
            )
    return violations
