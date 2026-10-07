"""Model provider plumbing. These use the fake provider and an httpx MockTransport —
they prove failure handling, NOT model quality."""

import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from app.config import Settings
from app.llm import DraftRequest, FakeProvider, ModelError, OpenAICompatibleProvider, build_provider, parse_model_json

from .conftest import triage

REQ = DraftRequest("northstar", "policy_supported", "return_eligible", "Approved draft.", [], {}, "msg")


def run(coro):
    return asyncio.run(coro)


def provider(handler, **kw):
    s = replace(Settings(), llm_provider="openai", llm_api_key="dummy", llm_model="m", llm_timeout_s=0.5, **kw)
    return OpenAICompatibleProvider(s, transport=httpx.MockTransport(handler))


def chat(content: str, status=200):
    return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})


@pytest.mark.parametrize("raw", ["", "not json", "[]", '{"x": 1}', '{"customer_response": ""}', '{"customer_response": 5}'])
def test_parse_rejects_malformed(raw):
    with pytest.raises(ModelError) as e:
        parse_model_json(raw)
    assert e.value.reason == "malformed"


def test_fake_is_deterministic():
    p = FakeProvider()
    assert run(p.draft(REQ)) == run(p.draft(REQ)) == "Approved draft."


def test_openai_success():
    p = provider(lambda req: chat(json.dumps({"customer_response": "Hello there."})))
    assert run(p.draft(REQ)) == "Hello there."


def test_openai_timeout():
    def h(req):
        raise httpx.ReadTimeout("slow", request=req)
    with pytest.raises(ModelError) as e:
        run(provider(h).draft(REQ))
    assert e.value.reason == "timeout"


def test_openai_malformed_content():
    with pytest.raises(ModelError) as e:
        run(provider(lambda r: chat("Sure! Here's your reply: ...")).draft(REQ))
    assert e.value.reason == "malformed"


def test_openai_malformed_envelope():
    with pytest.raises(ModelError):
        run(provider(lambda r: httpx.Response(200, json={"unexpected": True})).draft(REQ))


def test_openai_rate_limit_bounded_retry_then_success():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(429) if calls["n"] == 1 else chat(json.dumps({"customer_response": "Ok."}))

    assert run(provider(h, llm_max_retries=1).draft(REQ)) == "Ok."
    assert calls["n"] == 2


def test_openai_rate_limit_retries_are_capped():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(429)

    with pytest.raises(ModelError) as e:
        run(provider(h, llm_max_retries=10).draft(REQ))
    assert e.value.reason == "rate_limited" and calls["n"] == 3


def test_azure_request_shape():
    seen = {}

    def h(req):
        seen["url"], seen["key"] = str(req.url), req.headers.get("api-key")
        return chat(json.dumps({"customer_response": "Ok."}))

    s = replace(Settings(), llm_provider="azure_openai", llm_api_key="dummy", llm_base_url="https://x.openai.azure.com",
                llm_azure_deployment="gpt", llm_timeout_s=0.5)
    run(OpenAICompatibleProvider(s, transport=httpx.MockTransport(h)).draft(REQ))
    assert seen["url"].startswith("https://x.openai.azure.com/openai/deployments/gpt/chat/completions?api-version=")
    assert seen["key"] == "dummy"


def test_real_provider_requires_key():
    with pytest.raises(RuntimeError):
        build_provider(replace(Settings(), llm_provider="openai", llm_api_key=""))


def test_unsafe_model_output_is_blocked_end_to_end(make_client):
    c = make_client(model=FakeProvider(mode="unsafe"))
    r = triage(c, "northstar", "The jacket doesn't fit, I'd like to send it back.", "NS-88231").json()
    assert r["decision"] == "human_review" and r["model"]["fallback"] is True
    assert "refund" not in r["customer_response"].lower()
    assert "model_unsafe_output" in r["next_action"]


def test_slow_model_beyond_timeout_falls_back(make_client):
    c = make_client(model=FakeProvider(delay_s=0.5), llm_timeout_s=0.1)
    r = triage(c, "northstar", "The jacket doesn't fit, I'd like to send it back.", "NS-88231").json()
    assert r["decision"] == "human_review" and "model_timeout" in r["next_action"]


class ExplodingProvider:
    name = "boom"

    async def draft(self, req):
        raise RuntimeError("unexpected SDK bug")


def test_unexpected_provider_exception_is_bounded_and_audited(make_client):
    c = make_client(model=ExplodingProvider())
    r = triage(c, "northstar", "The jacket doesn't fit, I'd like to send it back.", "NS-88231")
    assert r.status_code == 200
    d = r.json()
    assert d["decision"] == "human_review" and d["model"]["fallback"] is True
    row = c.app.state.service.audit.get(d["request_id"])
    assert row["fallback_reason"] == "model_error"


def test_unexpected_pipeline_exception_is_bounded_and_audited(make_client, monkeypatch):
    c = make_client()
    import app.service as svc
    monkeypatch.setattr(svc, "resolve_facts", lambda *a, **k: (_ for _ in ()).throw(ValueError("bug")))
    r = triage(c, "northstar", "Return please", "NS-88231")
    assert r.status_code == 200 and r.json()["decision"] == "human_review"
    assert c.app.state.service.audit.get(r.json()["request_id"])["fallback_reason"] == "internal_error"


def test_retry_after_longer_than_budget_is_not_waited():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        return httpx.Response(429, headers={"retry-after": "30"})

    with pytest.raises(ModelError) as e:
        run(provider(h, llm_max_retries=2).draft(REQ))
    assert e.value.reason == "rate_limited" and calls["n"] == 1
