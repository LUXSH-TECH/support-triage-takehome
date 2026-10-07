"""Output validation for model drafts (enforced in code, outside the prompt).

A draft is rejected if it:
  * exceeds 400 characters or 3 sentences;
  * mentions the *other* retailer, its policy IDs, or text unique to its policies;
  * promises an action that policy never lets the service take on its own
    (approved/issued refunds, approved replacements, executed returns);
  * states a number that is not grounded in the reconciled facts, the cited policy
    text, or the rule thresholds (unsupported-claim heuristic);
  * leaks internal artefacts (prompt/system text, API keys).
"""

from __future__ import annotations

import re

MAX_CHARS = 400
MAX_SENTENCES = 3

RETAILER_NAMES = {"northstar": "Northstar", "cedar": "Cedar"}

PROMISE_PATTERNS = [
    r"\b(we|i)('ve| have| will|'ll| are going to)\s+(issue[d]?|process(ed)?|approve[d]?|send(ing)? you)\s+(a|your|the)?\s*(full\s+)?(refund|replacement)\b",
    r"\b(we|i)('ve| have| will|'ll)\s+(refund(ed)?|replace[d]?)\b",
    r"\brefund\s+(has been|is|was|will be)\s+(approved|issued|processed|authori[sz]ed|on its way)\b",
    r"\breplacement\s+(has been|is|was|will be)\s+(approved|issued|sent|shipped|authori[sz]ed|on its way)\b",
    r"\b(your )?return (has been|is) (approved|processed|accepted)\b",
    r"\bguarantee[d]?\b",
    r"\bas an exception\b|\bmake an exception\b",
    r"\b(you will|you'll|you are going to)\s+(receive|get)\s+(a|your|the)?\s*(full\s+)?(refund|replacement)\b",
    r"\b(refund|replacement)\s+(is|has been)?\s*(on (its|the) way|being (processed|shipped|sent|issued))\b",
    r"\b(refund|replacement|return)\s+(approved|issued|authori[sz]ed|granted)\b",
    r"\b(happy|glad|able) to (refund|replace)\b",
    r"\bextend(ed|ing)? (the|your) (return )?(window|deadline|period)\b",
    r"\bstore credit\b|\bgoodwill\b|\bcompensation\b",
]
LEAK_PATTERNS = [r"system prompt", r"\bapi[-_ ]?key\b", r"test-key-", r"ignore (all|previous) instructions"]

_PROMISE = [re.compile(p, re.I) for p in PROMISE_PATTERNS]
_LEAK = [re.compile(p, re.I) for p in LEAK_PATTERNS]
_NUMBER = re.compile(r"\b\d+\b")
_SENT = re.compile(r"[.!?]+(?=\s|$)")


def count_sentences(text: str) -> int:
    return max(1, len(_SENT.findall(text.strip()))) if text.strip() else 0


def validate_draft(
    text: str,
    *,
    retailer: str,
    other_retailer_policy_ids: list[str],
    other_retailer_texts: list[str],
    own_texts: list[str],
    allowed_numbers: set[int],
) -> list[str]:
    violations: list[str] = []
    if not isinstance(text, str) or not text.strip():
        return ["empty"]
    if len(text) > MAX_CHARS:
        violations.append("too_long")
    if count_sentences(text) > MAX_SENTENCES:
        violations.append("too_many_sentences")

    for key, name in RETAILER_NAMES.items():
        if key != retailer and re.search(rf"\b{name}\b", text, re.I):
            violations.append("cross_retailer_name")
    for pid in other_retailer_policy_ids:
        if pid.lower() in text.lower():
            violations.append("cross_retailer_policy_id")
    own = {c for t in own_texts for c in _clauses(t)}
    for t in other_retailer_texts:
        # A distinctive clause from the other retailer's policy (e.g. "within 30 days")
        # that is not also part of this retailer's own policy wording.
        for clause in _clauses(t) - own:
            if clause in text.lower():
                violations.append("cross_retailer_policy_text")

    if any(rx.search(text) for rx in _PROMISE):
        violations.append("unsupported_promise")
    if any(rx.search(text) for rx in _LEAK):
        violations.append("leak")

    for n in map(int, _NUMBER.findall(text)):
        if n not in allowed_numbers:
            violations.append(f"ungrounded_number:{n}")
    return sorted(set(violations))


_CLAUSE = re.compile(r"within \w+ days|more than \w+ days", re.I)


def _clauses(policy_text: str) -> set[str]:
    return {c.lower() for c in _CLAUSE.findall(policy_text)}
