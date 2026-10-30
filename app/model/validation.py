from __future__ import annotations

import re

from app.model.interface import DraftCitation, ModelDraft
from app.repositories.policy_repository import Policy


class InvalidDraft(ValueError):
    pass


PROMISE_PATTERNS = (
    r"\b(?:your|the) refund (?:is|has been|will be|was) approved\b",
    r"\bwe will refund\b",
    r"\b(?:your|the) replacement (?:is|has been|will be) approved\b",
    r"\bwe will replace (?:it|the item)\b",
)


def validate_draft(
    draft: object,
    retailer: str,
    policy: Policy | None,
    verified_facts: dict[str, object] | None = None,
    expected_response: str | None = None,
    expected_citation: tuple[str, str] | None = None,
) -> ModelDraft:
    if not isinstance(draft, ModelDraft):
        raise InvalidDraft("model output has an invalid structure")
    response = draft.response.strip()
    if not response or len(response) > 400:
        raise InvalidDraft("response is empty or too long")
    if expected_response is not None and response != expected_response:
        raise InvalidDraft("response is not the deterministic approved action")
    sentence_count = len(re.findall(r"[.!?](?:\s|$)", response))
    if sentence_count > 3:
        raise InvalidDraft("response has more than three sentences")
    if any(re.search(pattern, response, re.IGNORECASE) for pattern in PROMISE_PATTERNS):
        raise InvalidDraft("response makes an unsupported refund or replacement promise")

    policy_text = policy.text if policy is not None else ""
    verified_numbers = {
        str(value) for value in (verified_facts or {}).values() if isinstance(value, int)
    }
    for number in re.findall(r"\b(\d+)\s+days?\b", response, re.IGNORECASE):
        if number not in verified_numbers and number not in policy_text:
            raise InvalidDraft("response contains an unverified day count")

    other_retailer = "cedar" if retailer == "northstar" else "northstar"
    if re.search(rf"\b{other_retailer}\b", response, re.IGNORECASE):
        raise InvalidDraft("response names another retailer")

    for citation in draft.citations:
        if policy is None or policy.retailer != retailer or citation.policy_id != policy.policy_id:
            raise InvalidDraft("citation was not retrieved for this retailer")
        if citation.excerpt not in policy.text:
            raise InvalidDraft("citation is not a verbatim policy substring")
    if expected_citation is not None and DraftCitation(*expected_citation) not in draft.citations:
        raise InvalidDraft("response omitted the selected policy citation")
    return ModelDraft(response, draft.citations)