from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.models import Category


PATTERNS: dict[str, tuple[str, ...]] = {
    "returns": (
        r"\breturn(?:s|ing)?\b",
        r"\bsend(?:ing)? (?:it|this(?: [a-z]+)?|the [a-z]+)? ?back\b",
        r"\bdoesn['’]?t fit\b",
        r"\btoo (?:small|large|big)\b",
        r"\bwrong size\b",
        r"\bexchange\b",
    ),
    "damaged_item": (
        r"\bdamag(?:e|ed|ing)\b",
        r"\bbroken\b",
        r"\bdefective\b",
        r"\bcracked\b",
        r"\barrived (?:broken|damaged)\b",
        r"\bdoes not work\b",
    ),
    "shipping": (
        r"\blate\b",
        r"\bdelay(?:ed)?\b",
        r"\boverdue\b",
        r"\btracking\b",
        r"\bshipment\b",
        r"\bpackage (?:has not|hasn't|never) arrived\b",
        r"\bwhere is my (?:order|package|parcel)\b",
        r"\bdelivery (?:is |was )?(?:late|missing|delayed)\b",
    ),
}


@dataclass(frozen=True)
class Classification:
    category: Category
    matched_categories: tuple[str, ...]

    @property
    def mixed(self) -> bool:
        return len(self.matched_categories) > 1

    @property
    def ambiguous(self) -> bool:
        return not self.matched_categories


def classify(message: str) -> Classification:
    normalized = re.sub(r"\s+", " ", message.lower())
    scores = {
        category: sum(bool(re.search(pattern, normalized)) for pattern in patterns)
        for category, patterns in PATTERNS.items()
    }
    matches = tuple(category for category, score in scores.items() if score > 0)
    if len(matches) != 1:
        return Classification(category="other", matched_categories=matches)  # type: ignore[arg-type]
    return Classification(category=matches[0], matched_categories=matches)  # type: ignore[arg-type]