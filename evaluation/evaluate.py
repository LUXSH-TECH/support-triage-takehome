from __future__ import annotations

import json
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.classifier.baseline import classify
from app.config import ROOT, Settings
from app.main import create_app
from app.model.fake import FakeModelProvider
from app.repositories.policy_repository import PolicyRepository


CATEGORIES = ("returns", "damaged_item", "shipping", "other")
DATA_DIR = Path(__file__).parent


def classifier_report() -> tuple[dict[str, dict[str, float | int]], list[list[int]], int]:
    examples = [
        json.loads(line)
        for line in (DATA_DIR / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    matrix = [[0 for _ in CATEGORIES] for _ in CATEGORIES]
    for example in examples:
        predicted = classify(example["text"]).category
        matrix[CATEGORIES.index(example["label"])][CATEGORIES.index(predicted)] += 1

    metrics: dict[str, dict[str, float | int]] = {}
    for index, category in enumerate(CATEGORIES):
        true_positive = matrix[index][index]
        actual_count = sum(matrix[index])
        predicted_count = sum(row[index] for row in matrix)
        precision = true_positive / predicted_count if predicted_count else 0.0
        recall = true_positive / actual_count if actual_count else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        metrics[category] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": actual_count,
        }
    return metrics, matrix, len(examples)


def _new_client(database_url: str, model_mode: str = "normal") -> TestClient:
    settings = Settings(
        database_url=database_url,
        northstar_api_key="test-key-northstar-001",
        cedar_api_key="test-key-cedar-002",
        today=date(2025, 9, 1),
        erp_path=ROOT / "erp" / "orders.psv",
        fake_model_mode=model_mode,
    )
    return TestClient(
        create_app(settings, model_provider=FakeModelProvider(model_mode))
    )


def acceptance_report() -> tuple[dict[str, int], list[str]]:
    cases = json.loads((DATA_DIR / "cases.json").read_text(encoding="utf-8"))
    checks = defaultdict(int)
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="triage-evaluation-") as temp_dir:
        database_url = f"sqlite:///{(Path(temp_dir) / 'evaluation.db').as_posix()}"
        with _new_client(database_url) as client:
            for case in cases:
                retailer = case["retailer"]
                key = f"test-key-{retailer}-001" if retailer == "northstar" else "test-key-cedar-002"
                payload = {
                    "ticket_id": case["id"],
                    "order_ref": case["order_ref"],
                    "message": case["message"],
                }
                if "facts" in case:
                    payload["facts"] = case["facts"]
                response = client.post(
                    "/triage", headers={"X-API-Key": key}, json=payload
                )
                body = response.json()
                case_failures: list[str] = []
                if response.status_code != 200:
                    case_failures.append(f"HTTP {response.status_code}")
                if body.get("category") != case["expected_category"]:
                    case_failures.append("category")
                else:
                    checks["category_correct"] += 1
                if body.get("decision") != case["expected_decision"]:
                    case_failures.append("decision")
                else:
                    checks["decision_correct"] += 1

                citations = body.get("citations", [])
                actual_ids = {citation["policy_id"] for citation in citations}
                expected_id = case["expected_policy"]
                if actual_ids != ({expected_id} if expected_id else set()):
                    case_failures.append("policy_selection")
                else:
                    checks["policy_selection_correct"] += 1

                policies = client.app.state.policy_repository
                for citation in citations:
                    stored = policies.get_by_id(retailer, citation["policy_id"])
                    if stored is None or citation["excerpt"] not in stored.text:
                        case_failures.append("citation_exactness")
                        break
                else:
                    checks["citation_exactness_passed"] += 1

                serialized = json.dumps(body).lower()
                if any(term.lower() in serialized for term in case.get("must_not_contain", [])):
                    case_failures.append("retailer_isolation")
                elif "must_not_contain" in case:
                    checks["isolation_cases_passed"] += 1
                if body.get("model", {}).get("fallback") != case.get("expected_fallback", False):
                    case_failures.append("fallback_status")
                if len(body.get("customer_response", "")) > 400:
                    case_failures.append("response_length")
                if case_failures:
                    failures.append(f"{case['id']}: {', '.join(case_failures)}")

        with tempfile.TemporaryDirectory(prefix="triage-claim-check-") as temp_dir:
            db_url = f"sqlite:///{(Path(temp_dir) / 'claims.db').as_posix()}"
            with _new_client(db_url, "unsupported_claim") as client:
                body = client.post(
                    "/triage",
                    headers={"X-API-Key": "test-key-northstar-001"},
                    json={
                        "ticket_id": "unsupported-claim-check",
                        "order_ref": "NS-88231",
                        "message": "I want to return this item.",
                    },
                ).json()
                if body["model"]["fallback"] and body["decision"] == "human_review":
                    checks["unsupported_claim_rejected"] += 1
                else:
                    failures.append("unsupported_claim_probe: unsafe draft was not rejected")

    checks["acceptance_cases"] = len(cases)
    checks["isolation_failures"] = sum("retailer_isolation" in failure for failure in failures)
    checks["failed_cases"] = len(failures)
    return dict(checks), failures


def main() -> int:
    metrics, matrix, sample_count = classifier_report()
    checks, failures = acceptance_report()
    print("Support triage evaluation (deterministic fake provider; no real model calls)")
    print(f"Classifier samples: {sample_count}")
    print("Category              Precision  Recall  F1      Support")
    for category, values in metrics.items():
        print(
            f"{category:20} {values['precision']:>9.3f}  {values['recall']:>6.3f}  "
            f"{values['f1']:>6.3f}  {values['support']:>7}"
        )
    print("Confusion matrix (rows=actual, columns=predicted):")
    print("actual\\predicted   " + "  ".join(f"{category[:7]:>7}" for category in CATEGORIES))
    for category, row in zip(CATEGORIES, matrix):
        print(f"{category:18} " + "  ".join(f"{value:>7}" for value in row))
    print(f"Acceptance cases: {checks['acceptance_cases']}")
    for name in (
        "category_correct",
        "decision_correct",
        "policy_selection_correct",
        "citation_exactness_passed",
        "isolation_cases_passed",
        "unsupported_claim_rejected",
    ):
        print(f"{name.replace('_', ' ').title()}: {checks.get(name, 0)}")
    print(f"Retailer-isolation failures: {checks['isolation_failures']}")
    print(f"Failed cases: {checks['failed_cases']}")
    for failure in failures:
        print(f"FAIL: {failure}")
    print("Real-model evaluation: not performed; no real provider is configured.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())