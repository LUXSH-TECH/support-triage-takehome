import re


# Rule baseline. Pure function, no I/O, easy to evaluate.
RULES = {
    "damaged_item": re.compile(
        r"\b(damaged?|broken|broke|cracked?|defective|faulty|shattered|torn|dented|scratched|stained|not working|doesn'?t work)\b", re.I),
    "shipping": re.compile(
        r"\b(late|delayed?|overdue|tracking|lost|still waiting|not (yet )?(arrived|received|delivered)|hasn'?t (arrived|come|shown)|where is my|missing (package|parcel|order))\b", re.I),
    "returns": re.compile(
        r"\b(returns?|send (it |this )?back|ship (it |this )?back|refund|exchange|doesn'?t fit|wrong size|too (small|big|large|tight)|changed my mind|money back)\b", re.I),
}
UNSUPPORTED = re.compile(r"\b(warranty|price match|gift ?card|cancel (my )?(order|subscription)|change (my )?address)\b", re.I)


def classify(message: str) -> str:
    if UNSUPPORTED.search(message):
        return "other"
    hits = {cat for cat, rx in RULES.items() if rx.search(message)}
    if hits == {"returns", "damaged_item"}:
        return "damaged_item"  # N-RET/C-RET: "Damaged items follow the damaged-item policy"
    if len(hits) == 1:
        return hits.pop()
    return "other"  # no signal OR mixed issues -> unsupported/ambiguous -> human review