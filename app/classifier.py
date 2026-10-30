"""Non-LLM baseline classifier (keyword/regex rules).

Returns the top category, per-category scores, and two flags the service uses for
routing:
  * ``mixed``     — two or more operational categories matched (e.g. damaged AND late);
  * ``unsupported`` — an explicit out-of-scope topic (warranty, invoices, account, ...).

Rules are deliberately transparent so a reviewer can predict behaviour; the evaluation
(eval/run_eval.py) shows where they fail on paraphrases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PATTERNS: dict[str, list[str]] = {
    "returns": [
        r"\breturn(s|ed|ing)?\b",
        r"\bsend (it|this|them|these|the \w+) back\b",
        r"\bship (it|this|them) back\b",
        r"\bexchange\b",
        r"\b(doesn'?t|does not|didn'?t|did not) fit\b",
        r"\btoo (small|big|large|tight|loose)\b",
        r"\bwrong size\b",
        r"\bchanged my mind\b",
        r"\b(don'?t|do not) (want|need|like) (it|this|them)\b",
        r"\bmoney back\b",
        r"\brefund (it|this|my purchase|the item)\b",
    ],
    "damaged_item": [
        r"\bdamag(e|ed|es|ing)\b",
        r"\bbroken\b|\bbroke\b",
        r"\bcrack(ed|s)?\b",
        r"\bshatter(ed)?\b",
        r"\bsmashed\b",
        r"\bdent(ed|s)?\b",
        r"\bscratch(ed|es)?\b",
        r"\btorn\b|\bripped\b",
        r"\bin pieces\b",
        r"\bleak(ing|ed|s)?\b",
        r"\bdefective\b|\bfaulty\b",
    ],
    "shipping": [
        r"\bwhere is my (order|package|parcel|delivery)\b",
        r"\b(hasn'?t|has not|haven'?t|have not|never|not yet|still not) (arrived|come|shown up|been delivered|received)\b",
        r"\bnot (arrived|received|delivered)\b",
        r"\b(late|delayed|overdue)\b",
        r"\bstill waiting\b",
        r"\btracking\b",
        r"\blost in (transit|the post|the mail)\b",
        r"\bdelivery date\b.*\b(passed|missed|gone)\b",
    ],
}

# Out-of-scope topics that override an operational match ("it broke — is it under warranty?").
UNSUPPORTED_STRONG = [
    r"\bwarrant(y|ies)\b",
    r"\bpassword\b|\blog ?in\b",
    r"\bgift card\b|\bvoucher\b|\bpromo code\b|\bdiscount code\b",
    r"\bsubscription\b",
    r"\b(policies|policy document|terms and conditions)\b",
    r"\bcompetitor\b|\bprice match\b",
]
# Topics that are out of scope only when nothing operational is asked
# ("return it, I have the receipt" is still a return).
UNSUPPORTED_WEAK = [r"\binvoice\b|\breceipt\b|\bvat\b", r"\baccount\b|\bprofile\b"]

# Negated or incidental mentions removed before matching: "not damaged", "no delay",
# "sorry for the late reply".
NOISE = re.compile(
    r"\b(not|no|isn'?t|wasn'?t|aren'?t|never|without)\s+(any\s+)?"
    r"(damage[ds]?|damaged|broken|cracked|scratch(ed|es)?|late|delayed|delay)\b"
    r"|\blate (reply|response)\b",
    re.I,
)

_COMPILED = {c: [re.compile(p, re.I) for p in ps] for c, ps in PATTERNS.items()}
_STRONG = [re.compile(p, re.I) for p in UNSUPPORTED_STRONG]
_WEAK = [re.compile(p, re.I) for p in UNSUPPORTED_WEAK]


@dataclass(frozen=True)
class Classification:
    category: str
    scores: dict[str, int]
    mixed: bool
    unsupported: bool


def classify(message: str) -> Classification:
    text = NOISE.sub(" ", message)
    scores = {c: sum(1 for rx in rxs if rx.search(text)) for c, rxs in _COMPILED.items()}
    matched = [c for c, s in scores.items() if s > 0]
    unsupported = any(rx.search(text) for rx in _STRONG) or (
        not matched and any(rx.search(text) for rx in _WEAK)
    )

    if not matched:
        return Classification("other", scores, mixed=False, unsupported=unsupported)
    if unsupported:
        # e.g. "my kettle broke, is it under warranty?" -> out of scope, not damaged-item.
        return Classification("other", scores, mixed=len(matched) > 1, unsupported=True)

    # "returns" is the generic intent behind many damaged/shipping complaints ("it's
    # broken, I want to return it"). Damaged-item policy governs damaged returns, so a
    # damaged+returns match is not "mixed" — it is damaged_item.
    if set(matched) == {"returns", "damaged_item"}:
        return Classification("damaged_item", scores, mixed=False, unsupported=False)

    top = max(matched, key=lambda c: (scores[c], -list(PATTERNS).index(c)))
    return Classification(top, scores, mixed=len(matched) > 1, unsupported=False)
