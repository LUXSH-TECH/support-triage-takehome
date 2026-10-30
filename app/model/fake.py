from __future__ import annotations

from app.model.interface import DraftCitation, ModelContext, ModelDraft


class FakeModelProvider:
    name = "fake"

    def __init__(self, mode: str = "normal") -> None:
        self.mode = mode

    def draft(self, context: ModelContext) -> ModelDraft:
        if self.mode == "timeout":
            raise TimeoutError("simulated model timeout")
        if self.mode == "malformed":
            return {"unexpected": "shape"}  # type: ignore[return-value]

        if self.mode == "unsupported_claim":
            return ModelDraft("Your refund is approved.", ())

        if self.mode == "invalid_citation":
            return ModelDraft(
                context.next_action,
                (DraftCitation("N-RET", "This excerpt is not in the selected policy."),),
            )

        citations = ()
        if context.policy_id and context.citation_excerpt:
            citations = (DraftCitation(context.policy_id, context.citation_excerpt),)
        return ModelDraft(context.next_action, citations)