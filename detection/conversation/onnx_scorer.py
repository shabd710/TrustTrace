"""
Trained-ONNX scorer for the Tier 1 cascade blend.

Mirrors llm_runtime.py's contract exactly, deliberately:

    score_candidates_with_onnx(text, tactic_ids) -> Optional[list[OnnxRefinement]]

Returns None whenever the model or onnxruntime is unavailable, so every
existing test and the whole CPU-only/sandbox path keep working untouched. The
cascade already knows how to handle a None here.

Where the model comes from
--------------------------
Exported by the trusttrace_ml_training framework:
    python -m export.export_model --backend transformer   -> transformer.int8.onnx
    python -m export.export_model --backend baseline      -> scam_classifier.int8.onnx

Point this module at it:
    set TRUSTTRACE_ONNX_MODEL=C:\\path\\to\\transformer.int8.onnx      (Windows)
    export TRUSTTRACE_ONNX_MODEL=/path/to/transformer.int8.onnx       (Linux/mac)

Both export signatures are supported and auto-detected (runtime_contract.md):
  - transformer: input_ids/attention_mask -> bin_logits, tac_logits  (needs a tokenizer)
  - baseline:    input (string)           -> label, probabilities    (no tokenizer)

Confidence semantics
--------------------
transformer: conf(tactic) = P(scam) * P(tactic | text), from the two heads.
             A joint probability — the message is a scam AND it's this tactic.
baseline:    no tactic head exists, so P(scam) is applied uniformly to every
             requested tactic. Cruder by construction; documented, not hidden.

Standing rules this file must not break
--------------------------------------
- The model PROPOSES; it never decides. Every blended candidate still passes the
  NLI entailment gate and the confidence gate downstream (spec 2.5).
- The keyword rule engine stays a floor: this only ever runs on candidates Tier 0
  already surfaced. It cannot introduce a tactic the cues never matched.
- No threshold here is scaled by battery/thermal or any device state
  (STRICT SUMMARY).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

# Same 6-class order as the training taxonomy (datahub/taxonomy/schema.py) and
# detection/conversation/tactic_taxonomy.py's scoreable set. Index order is a
# frozen contract -- changing it is a MAJOR version bump (runtime_contract.md).
TACTIC_ORDER = [
    "none",
    "urgency_injection",
    "isolation_instruction",
    "authority_impersonation",
    "payment_channel_funneling",
    "too_good_to_be_true",
]

ONNX_MODEL_PATH = os.environ.get("TRUSTTRACE_ONNX_MODEL", "")
ENCODER_NAME = os.environ.get(
    "TRUSTTRACE_ONNX_ENCODER", "intfloat/multilingual-e5-base"
)
MAX_LEN = int(os.environ.get("TRUSTTRACE_ONNX_MAXLEN", "128"))

_SESSION = None
_BACKEND = None
_TOKENIZER = None
_INIT_FAILED = False


@dataclass
class OnnxRefinement:
    tactic_id: str
    confidence: float


def _softmax(x):
    import numpy as np

    e = np.exp(x - np.max(x, axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)


def _available() -> bool:
    if _INIT_FAILED or not ONNX_MODEL_PATH:
        return False
    return os.path.isfile(ONNX_MODEL_PATH)


def _init() -> bool:
    """Lazy one-time load. Any failure disables this path permanently rather
    than raising into the cascade -- a missing optional model must never break
    detection."""
    global _SESSION, _BACKEND, _TOKENIZER, _INIT_FAILED
    if _SESSION is not None:
        return True
    if _INIT_FAILED or not _available():
        return False
    try:
        import onnxruntime as ort

        sess = ort.InferenceSession(ONNX_MODEL_PATH)
        names = {i.name: i for i in sess.get_inputs()}
        if "input_ids" in names:
            from transformers import AutoTokenizer

            _TOKENIZER = AutoTokenizer.from_pretrained(ENCODER_NAME)
            _BACKEND = "transformer"
        elif names[list(names)[0]].type == "tensor(string)":
            _BACKEND = "baseline"
        else:
            _INIT_FAILED = True
            return False
        _SESSION = sess
        return True
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("ONNX INIT ERROR:", e)
        _INIT_FAILED = True
        return False


def _score_transformer(text: str) -> Optional[dict[str, float]]:
    import numpy as np

    enc = _TOKENIZER(
        [text],
        truncation=True,
        padding="max_length",
        max_length=MAX_LEN,
        return_tensors="np",
    )
    feeds = {
        "input_ids": enc["input_ids"].astype(np.int64),
        "attention_mask": enc["attention_mask"].astype(np.int64),
    }
    bin_logits, tac_logits = _SESSION.run(None, feeds)
    p_scam = float(_softmax(bin_logits)[0][1])
    tac_probs = _softmax(tac_logits)[0]
    # joint: scam AND this tactic
    return {
        TACTIC_ORDER[i]: p_scam * float(tac_probs[i])
        for i in range(min(len(TACTIC_ORDER), len(tac_probs)))
    }


def _score_baseline(text: str) -> Optional[dict[str, float]]:
    import numpy as np

    name = _SESSION.get_inputs()[0].name
    out = _SESSION.run(None, {name: np.array([[text]], dtype=object)})
    p_scam = float(out[1][0][1])
    # No tactic head: uniform P(scam) across whatever Tier 0 proposed.
    return {t: p_scam for t in TACTIC_ORDER if t != "none"}


def score_candidates_with_onnx(
    text: str, tactic_ids: list[str]
) -> Optional[list[OnnxRefinement]]:
    """Per-tactic confidences from the trained model, or None if unavailable.

    Mirrors refine_candidates_with_llm()'s signature so the cascade blends both
    the same way.
    """
    if not tactic_ids or not _init():
        return None
    try:
        conf = (
            _score_transformer(text)
            if _BACKEND == "transformer"
            else _score_baseline(text)
        )
    except Exception:
        return None
    if not conf:
        return None
    return [
        OnnxRefinement(tactic_id=t, confidence=float(conf.get(t, 0.0)))
        for t in tactic_ids
    ]


def backend_in_use() -> Optional[str]:
    """'transformer' | 'baseline' | None -- for diagnostics/eval reporting."""
    return _BACKEND if _init() else None
