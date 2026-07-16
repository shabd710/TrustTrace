"""
Labeled manipulation-detection corpus.

Spec ref: PDF Section 4: "a labeled corpus built from public FTC/IC3
case-narrative writeups plus a self-authored set of synthetic
scam-conversation scenarios." This is the self-authored synthetic half --
small, but real labels used by real evaluate.py assertions below, plus
equity metadata (age_bracket/language) per spec 4's equity_eval.py
requirement, and one adversarial-evasion example per spec 10.1 (a
low-signal, non-randomized message that should NOT fire Tier 0 alone).
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class LabeledExample:
    text: str
    is_manipulation: bool
    age_bracket: str    # equity slice, spec 4
    language: str        # equity slice, spec 4
    note: str = ""


MANIPULATION_CORPUS: list[LabeledExample] = [
    # --- true positives ---
    LabeledExample("This is the IRS. Wire the money now or you'll be arrested. Do not tell your bank.", True, "65+", "en"),
    LabeledExample("Only accept gift card payment, don't mention this to anyone, act now before it's too late.", True, "18-64", "en"),
    LabeledExample("Guaranteed 40% return, no risk, act now to claim your spot, don't tell your family about this opportunity.", True, "18-64", "en"),
    LabeledExample("I've never felt this way about anyone before. I need you to wire the money today, it's urgent, and please don't tell your family about us yet.", True, "65+", "en"),
    LabeledExample("This is your bank's fraud department, we need you to buy a gift card immediately to secure your account.", True, "65+", "hi"),

    # --- true negatives (benign, including edge cases the system must NOT flag) ---
    LabeledExample("Hey, are we still on for lunch tomorrow?", False, "18-64", "en"),
    LabeledExample("Take your time getting back to me, there's no rush at all.", False, "18-64", "en"),
    LabeledExample("I would never send a gift card to someone I just met online.", False, "18-64", "en"),
    LabeledExample("What if someone asked me to wire money? Would that be a scam?", False, "18-64", "en"),
    LabeledExample("My mom is in the hospital, please call me back as soon as you can, it's urgent.", False, "65+", "en"),  # real emergency: urgent but no isolation/payment funneling
    LabeledExample("Please don't tell my parents I got a B on the exam, they'll be upset.", False, "13-17", "en"),  # isolation-shaped phrasing, non-financial, benign context

    # --- adversarial evasion example, spec 10.1: ordinary well-written
    # low-signal language, no per-message cue words at all, that ONLY
    # becomes clear as a scam across a narrative arc (not testable as a
    # single-message Tier 0 case -- included here as documentation of the
    # limitation, asserted separately in evaluate.py's adversarial slice).
    LabeledExample("I'm so glad we met. I'd love to tell you more about my situation soon.", True, "18-64", "en",
                    note="adversarial evasion example (spec 10.1): week-1 grooming opener -- single-message Tier 0 will NOT catch this by design; only narrative-arc tracking across turns can."),
]
