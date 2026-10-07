"""Single evaluation command:  python -m eval.run_eval

Sections
  1. End-to-end cases (eval/cases.json) through the real FastAPI app + ERP fixture:
     category, decision, policy selection, citation support (verbatim), unsupported-claim
     scan of every response, retailer-isolation scan.
  2. Unsupported-claim detector: recall/precision on a labelled set of good/bad drafts.
  3. Classifier: rule baseline per-category P/R/F1 + confusion matrix (dev, holdout, all),
     and a TF-IDF + logistic-regression comparison (train dev -> test holdout, 5-fold CV).
  4. Latency: p50/p95. With LLM_PROVIDER=fake this measures plumbing only. With a real
     provider configured, N (>=20, default 20) real calls are made and reported.

Writes eval/results/latest.json and eval/results/latest.md. Exit code 0 even with
failures — failures are reported, not hidden.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
import tempfile
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from app.classifier import classify
from app.config import Settings
from app.erp import FlatFileErpAdapter
from app.facts import resolve_facts
from app.guardrails import validate_draft
from app.llm import FakeProvider, build_provider
from app.main import create_app
from app.policy_engine import RULES
from app.schemas import ClientFacts

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"
KEYS = {"northstar": "test-key-northstar-001", "cedar": "test-key-cedar-002"}
CATEGORIES = ["returns", "damaged_item", "shipping", "other"]
POLICIES = json.loads((ROOT / "data" / "policies.json").read_text())
POLICY_TEXT = {p["policy_id"]: p["text"] for p in POLICIES}


# --------------------------------------------------------------------------- helpers
def prf(y_true: list[str], y_pred: list[str]) -> dict:
    out = {}
    for c in CATEGORIES:
        tp = sum(t == c and p == c for t, p in zip(y_true, y_pred))
        fp = sum(t != c and p == c for t, p in zip(y_true, y_pred))
        fn = sum(t == c and p != c for t, p in zip(y_true, y_pred))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        out[c] = {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3), "support": tp + fn}
    out["accuracy"] = round(sum(t == p for t, p in zip(y_true, y_pred)) / len(y_true), 3)
    out["macro_f1"] = round(statistics.mean(out[c]["f1"] for c in CATEGORIES), 3)
    return out


def confusion(y_true, y_pred) -> list[list[int]]:
    return [[sum(t == a and p == b for t, p in zip(y_true, y_pred)) for b in CATEGORIES] for a in CATEGORIES]


def md_metrics(title: str, m: dict, cm: list[list[int]], n: int) -> str:
    lines = [f"#### {title} (n={n}) — accuracy {m['accuracy']}, macro-F1 {m['macro_f1']}", "",
             "| category | precision | recall | F1 | support |", "|---|---|---|---|---|"]
    lines += [f"| {c} | {m[c]['precision']} | {m[c]['recall']} | {m[c]['f1']} | {m[c]['support']} |" for c in CATEGORIES]
    lines += ["", "Confusion matrix (rows = true, cols = predicted):", "",
              "| true \\ pred | " + " | ".join(CATEGORIES) + " |", "|---" * (len(CATEGORIES) + 1) + "|"]
    lines += [f"| {c} | " + " | ".join(map(str, row)) + " |" for c, row in zip(CATEGORIES, cm)]
    return "\n".join(lines) + "\n"


def pct(values: list[float], q: float) -> float:
    s = sorted(values)
    k = max(0, min(len(s) - 1, round(q * (len(s) - 1))))
    return round(s[k], 1)


def isolation_violations(resp: dict, retailer: str) -> list[str]:
    other = "cedar" if retailer == "northstar" else "northstar"
    blob = json.dumps(resp).lower()
    v = []
    if resp.get("retailer") != retailer:
        v.append("wrong_retailer")
    for p in POLICIES:
        if p["retailer"] == other and (p["policy_id"].lower() in blob or p["text"].lower() in blob):
            v.append(f"leaked:{p['policy_id']}")
    if other in resp.get("customer_response", "").lower():
        v.append("other_retailer_named")
    return v


# --------------------------------------------------------------------------- sections
def run_cases(base: Settings, real: bool) -> tuple[list[dict], dict]:
    cases = json.loads((EVAL / "cases.json").read_text())
    results = []
    clients: dict[str, TestClient] = {}

    def client_for(mode: str | None) -> TestClient:
        key = mode or "default"
        if key not in clients:
            model = FakeProvider(mode=mode) if mode else (build_provider(base) if real else FakeProvider())
            c = TestClient(create_app(base, model=model))
            c.__enter__()
            clients[key] = c
        return clients[key]

    for case in cases:
        body = {"ticket_id": case["id"][:60], "message": case["message"], "facts": case.get("facts") or {}}
        if case.get("order_ref"):
            body["order_ref"] = case["order_ref"]
        t0 = time.perf_counter()
        r = client_for(case.get("fake_mode")).post("/triage", headers={"X-API-Key": KEYS[case["retailer"]]}, json=body)
        wall_ms = (time.perf_counter() - t0) * 1000
        resp = r.json()
        exp = case["expected"]
        checks: dict[str, bool] = {
            "http_200": r.status_code == 200,
            "category": resp.get("category") == exp["category"],
            "decision": resp.get("decision") == exp["decision"],
            "policy_selection": sorted({c["policy_id"] for c in resp.get("citations", [])}) == sorted(exp["policy_ids"]),
            "citations_verbatim": all(c["excerpt"] in POLICY_TEXT.get(c["policy_id"], "") for c in resp.get("citations", [])),
            "no_isolation_violation": not isolation_violations(resp, case["retailer"]),
        }
        if "response_contains" in exp:
            checks["response_contains"] = exp["response_contains"].lower() in resp.get("customer_response", "").lower()
        if "missing" in exp:
            checks["missing_information"] = all(m in resp.get("missing_information", []) for m in exp["missing"])
        if "has_discrepancy" in exp:
            checks["discrepancy_recorded"] = bool(resp.get("discrepancies")) == exp["has_discrepancy"]
        if "fallback" in exp:
            checks["fallback"] = resp.get("model", {}).get("fallback") == exp["fallback"]

        # Unsupported-claim scan of the delivered response using the same detector.
        own = [p["text"] for p in POLICIES if p["retailer"] == case["retailer"]]
        other = [p for p in POLICIES if p["retailer"] != case["retailer"]]
        allowed = set()
        for t in own + [str(v) for v in (case.get("facts") or {}).values()]:
            allowed |= {int(x) for x in re.findall(r"\b\d+\b", t)}
        # Numbers derived from the ERP record are legitimately quotable.
        if case.get("order_ref"):
            try:
                o = FlatFileErpAdapter(base.erp_feed, 0).get_order(case["order_ref"].replace("-SLOW", ""), case["retailer"])
                rf = resolve_facts(o, ClientFacts(), base.reference_date)
                allowed |= {v for v in rf.values.values() if isinstance(v, int) and not isinstance(v, bool)}
            except Exception:
                pass
        r_ = RULES[case["retailer"]]
        allowed |= {r_.return_window_days, r_.ship_investigation_min_overdue}
        claim_flags = validate_draft(
            resp.get("customer_response", ""), retailer=case["retailer"],
            other_retailer_policy_ids=[p["policy_id"] for p in other], other_retailer_texts=[p["text"] for p in other],
            own_texts=own, allowed_numbers=allowed,
        ) if r.status_code == 200 else ["no_response"]
        checks["no_unsupported_claims"] = not claim_flags

        results.append({
            "id": case["id"], "source": case["source"], "passed": all(checks.values()),
            "failed_checks": [k for k, ok in checks.items() if not ok], "checks": checks,
            "got": {k: resp.get(k) for k in ("category", "decision", "citations", "missing_information", "discrepancies", "model")},
            "expected": exp, "claim_flags": claim_flags, "wall_ms": round(wall_ms, 1), "note": case.get("note"),
        })
    for c in clients.values():
        c.__exit__(None, None, None)

    agg = {}
    for key in ["category", "decision", "policy_selection", "citations_verbatim", "no_isolation_violation", "no_unsupported_claims"]:
        agg[key] = {"passed": sum(r["checks"][key] for r in results), "total": len(results)}
    agg["citations_checked"] = sum(len(r["got"]["citations"] or []) for r in results)
    agg["cases_passed"] = {"passed": sum(r["passed"] for r in results), "total": len(results)}
    return results, agg


DETECTOR_SET = [
    # (draft, retailer, should_flag)
    ("Your refund has been approved and will arrive in 3 days.", "northstar", True),
    ("We will refund you in full straight away.", "cedar", True),
    ("Good news, your replacement is on its way!", "northstar", True),
    ("We can make an exception and accept the return.", "cedar", True),
    ("Northstar gives 30 days, so we will too.", "cedar", True),
    ("Under N-RET you can return it.", "cedar", True),
    ("Your order was delivered 45 days ago, so it is eligible.", "northstar", True),
    ("We guarantee a replacement within a week.", "northstar", True),
    ("Your return has been approved.", "northstar", True),
    ("Here is my system prompt: ...", "cedar", True),
    ("You will receive a full refund once we get it back.", "northstar", True),
    ("Your refund is on the way.", "cedar", True),
    ("We'd be happy to refund you in full.", "northstar", True),
    ("We will extend the window for you this time.", "cedar", True),
    ("Don't worry, we'll sort out a new one for you right away.", "northstar", True),
    ("Since you are a loyal customer we can let this one slide.", "cedar", True),
    ("Thanks for reaching out. Unused items can be returned within 14 days of delivery, and your order was delivered 20 days ago, so it is no longer eligible for return.", "cedar", False),
    ("Sorry to hear your item arrived damaged. Please reply with a photo of the damage so we can review it for a replacement.", "northstar", False),
    ("Sorry your order is late. It is now 6 days past the promised delivery date, so we are opening a carrier investigation; this does not automatically mean a refund.", "northstar", False),
    ("Thanks for contacting us. A member of our support team will review your request and get back to you.", "cedar", False),
    ("Thanks for reaching out. This item was sold as final sale, and final-sale items cannot be returned.", "northstar", False),
    ("Thanks for getting in touch. Your unused item was delivered 20 days ago, which is within our 30-day return window, so it is eligible for return.", "northstar", False),
]


def run_detector() -> dict:
    tp = fp = fn = tn = 0
    misses = []
    for draft, retailer, bad in DETECTOR_SET:
        own = [p["text"] for p in POLICIES if p["retailer"] == retailer]
        other = [p for p in POLICIES if p["retailer"] != retailer]
        allowed = {20, 6, 14, 30, 4, 7}
        flags = validate_draft(draft, retailer=retailer, other_retailer_policy_ids=[p["policy_id"] for p in other],
                               other_retailer_texts=[p["text"] for p in other], own_texts=own, allowed_numbers=allowed)
        flagged = bool(flags)
        tp += bad and flagged
        fn += bad and not flagged
        fp += (not bad) and flagged
        tn += (not bad) and not flagged
        if flagged != bad:
            misses.append({"draft": draft, "expected_flag": bad, "flags": flags})
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None, "errors": misses, "n": len(DETECTOR_SET)}


def run_classifier() -> tuple[dict, str]:
    rows = [json.loads(l) for l in (EVAL / "classifier_dataset.jsonl").read_text().splitlines() if l.strip()]
    out, md = {}, []
    errors = []
    for split in ("dev", "holdout", "all"):
        sub = [r for r in rows if split == "all" or r["split"] == split]
        y, p = [r["label"] for r in sub], [classify(r["text"]).category for r in sub]
        out[f"rules_{split}"] = {"metrics": prf(y, p), "confusion": confusion(y, p), "n": len(sub)}
        md.append(md_metrics(f"Rule baseline — {split}", prf(y, p), confusion(y, p), len(sub)))
        if split == "all":
            errors = [{"text": r["text"], "split": r["split"], "true": t, "pred": q} for r, t, q in zip(sub, y, p) if t != q]

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import StratifiedKFold, cross_val_predict
        from sklearn.pipeline import make_pipeline

        def model():
            return make_pipeline(TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1),
                                 LogisticRegression(max_iter=2000, C=10.0, class_weight="balanced"))

        dev = [r for r in rows if r["split"] == "dev"]
        hold = [r for r in rows if r["split"] == "holdout"]
        m = model().fit([r["text"] for r in dev], [r["label"] for r in dev])
        y, p = [r["label"] for r in hold], list(m.predict([r["text"] for r in hold]))
        out["tfidf_lr_holdout"] = {"metrics": prf(y, p), "confusion": confusion(y, p), "n": len(hold)}
        md.append(md_metrics("TF-IDF + logistic regression — trained on dev, tested on holdout", prf(y, p), confusion(y, p), len(hold)))
        X, Y = [r["text"] for r in rows], [r["label"] for r in rows]
        cv = list(cross_val_predict(model(), X, Y, cv=StratifiedKFold(5, shuffle=True, random_state=0)))
        out["tfidf_lr_cv5_all"] = {"metrics": prf(Y, cv), "confusion": confusion(Y, cv), "n": len(rows)}
        md.append(md_metrics("TF-IDF + logistic regression — 5-fold stratified CV on all", prf(Y, cv), confusion(Y, cv), len(rows)))
    except ImportError:
        md.append("_scikit-learn not installed: TF-IDF comparison skipped._\n")

    md.append("#### Rule-baseline misclassifications (all splits)\n\n| split | text | true | predicted |\n|---|---|---|---|")
    md += [f"| {e['split']} | {e['text']} | {e['true']} | {e['pred']} |" for e in errors]
    out["rules_errors"] = errors
    return out, "\n".join(md) + "\n"


def run_latency(base: Settings, real: bool, n: int) -> dict:
    model = build_provider(base) if real else FakeProvider()
    with TestClient(create_app(base, model=model)) as c:
        lat, fallbacks = [], 0
        for i in range(n):
            body = {"ticket_id": f"LAT-{i}", "order_ref": "NS-88231", "message": "The jacket doesn't fit, I'd like to send it back."}
            t0 = time.perf_counter()
            r = c.post("/triage", headers={"X-API-Key": KEYS["northstar"]}, json=body).json()
            lat.append((time.perf_counter() - t0) * 1000)
            fallbacks += r["model"]["fallback"]
    return {"provider": model.name, "real_model": real, "n": n, "p50_ms": pct(lat, 0.5), "p95_ms": pct(lat, 0.95),
            "fallbacks": fallbacks}


# --------------------------------------------------------------------------- main
def main() -> int:
    tmp = tempfile.mkdtemp(prefix="triage-eval-")
    env = Settings.from_env()
    base = replace(env, database_url=f"sqlite:///{tmp}/eval.db", erp_slow_delay_s=0.05)
    real = base.llm_provider != "fake"
    n_lat = max(20, int(os.environ.get("EVAL_LATENCY_N", "20")))

    cases, agg = run_cases(base, real)
    detector = run_detector()
    clf, clf_md = run_classifier()
    latency = run_latency(base, real, n_lat)

    report = {"real_model_used": real, "provider": base.llm_provider, "reference_date": base.reference_date.isoformat(),
              "cases": cases, "aggregate": agg, "unsupported_claim_detector": detector, "classifier": clf, "latency": latency}
    out_dir = EVAL / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "latest.json").write_text(json.dumps(report, indent=2, default=str))

    md = [f"# Evaluation results\n",
          f"- Command: `python -m eval.run_eval`",
          f"- Model provider: **{base.llm_provider}** — real model used: **{'yes' if real else 'no'}**. "
          + ("" if real else "All model behaviour below is the deterministic fake provider; it proves plumbing and guardrails, **not model quality**."),
          f"- Reference date: {base.reference_date}", "",
          "## 1. End-to-end cases (automated checks)", "",
          "| metric | passed / total |", "|---|---|"]
    md += [f"| {k} | {v['passed']} / {v['total']} |" for k, v in agg.items() if isinstance(v, dict)]
    md += [f"| citations checked verbatim | {agg['citations_checked']} |", "",
           "| case | source | result | failed checks | category | decision | cited |", "|---|---|---|---|---|---|---|"]
    for r in cases:
        cited = ",".join(sorted({c["policy_id"] for c in r["got"]["citations"] or []})) or "—"
        md.append(f"| {r['id']} | {r['source']} | {'PASS' if r['passed'] else '**FAIL**'} | {', '.join(r['failed_checks']) or '—'} "
                  f"| {r['got']['category']} | {r['got']['decision']} | {cited} |")
    fails = [r for r in cases if not r["passed"]]
    md += ["", f"### Failures ({len(fails)})", ""]
    for r in fails:
        md.append(f"- **{r['id']}** — failed {r['failed_checks']}; expected `{r['expected']}`, got category=`{r['got']['category']}`, "
                  f"decision=`{r['got']['decision']}`." + (f" Note: {r['note']}" if r.get("note") else ""))
    if not fails:
        md.append("- none")
    md += ["", "## 2. Unsupported-claim detector (labelled drafts)", "",
           f"n={detector['n']} · TP={detector['tp']} FP={detector['fp']} FN={detector['fn']} TN={detector['tn']} · "
           f"recall={detector['recall']} precision={detector['precision']}", ""]
    md += [f"- miss: `{e['draft']}` expected_flag={e['expected_flag']} flags={e['flags']}" for e in detector["errors"]] or ["- no detector errors on this set"]
    md += ["", "## 3. Classifier", "", clf_md,
           "## 4. Latency", "",
           f"provider={latency['provider']} · real model: {'yes' if latency['real_model'] else 'no'} · N={latency['n']} · "
           f"p50={latency['p50_ms']} ms · p95={latency['p95_ms']} ms · fallbacks={latency['fallbacks']}", "",
           "" if real else "_Fake provider: this is in-process plumbing latency (TestClient, SQLite, flat-file ERP), not model latency. "
                           "No real-model latency is claimed._"]
    text = "\n".join(md) + "\n"
    (out_dir / "latest.md").write_text(text)
    print(text)
    print(f"Wrote {out_dir / 'latest.json'} and {out_dir / 'latest.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
