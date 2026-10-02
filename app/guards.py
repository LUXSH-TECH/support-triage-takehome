import re

RETAILERS = ("northstar", "cedar")

INJECTION = re.compile(
    r"ignore (all |any |the )?(previous|prior|above|earlier)( \w+)? (instructions|rules|prompts?)"
    r"|disregard (the |your )?(rules|polic(y|ies)|instructions)"
    r"|system prompt|developer mode|you are now|override (the )?(polic(y|ies)|rules)"
    r"|reveal (your|the) (prompt|instructions)", re.I)

PROMISE = re.compile(
    r"\b(we (have|'ve|will|'ll) (approved|refund|refunded|replace|replaced|issue|issued)"
    r"|(has|have) been (approved|refunded|replaced|issued)"
    r"|will be (approved|refunded|replaced|issued)"
    r"|full refund|guarantee)", re.I)


def suspicious(message: str) -> bool:
    return bool(INJECTION.search(message))


def mentions_other_retailer(message: str, retailer: str) -> bool:
    other = next(r for r in RETAILERS if r != retailer)
    return bool(re.search(rf"\b{other}\b", message, re.I))


def validate_draft(text: object, retailer: str) -> str:
    """Validate model output. Raises ValueError -> service treats it as a model failure."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty or non-string draft")
    text = text.strip()
    if len(text) > 400:
        raise ValueError("draft longer than 400 chars")
    if len(re.findall(r"[.!?](?:\s|$)", text)) > 3:
        raise ValueError("draft longer than 3 sentences")
    if PROMISE.search(text):
        raise ValueError("draft makes an unsupported promise")
    other = next(r for r in RETAILERS if r != retailer)
    if re.search(rf"\b{other}\b", text, re.I) or re.search(rf"\b{other[0].upper()}-(RET|DMG|SHIP)\b", text):
        raise ValueError("draft leaks another retailer")
    return text