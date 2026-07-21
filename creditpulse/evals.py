"""Evaluation harness for CreditPulse."""

from __future__ import annotations

import json
from pathlib import Path

from creditpulse.covenants import CovenantResult, breached_months
from creditpulse.policy import ExtractedField, MemoClaim, memo_claim_is_supported


def extraction_accuracy(extracted: list[ExtractedField], expected: dict[str, object]) -> float:
    extracted_by_name = {field.name: field for field in extracted}
    correct = sum(1 for name, value in expected.items() if name in extracted_by_name and extracted_by_name[name].value == value and extracted_by_name[name].citation)
    return correct / len(expected) if expected else 1.0


def covenant_precision_recall(results: list[CovenantResult], ground_truth_path: str | Path) -> dict[str, float]:
    truth = json.loads(Path(ground_truth_path).read_text())
    expected = set(truth["breach_months"])
    predicted = breached_months(results)
    true_positive = len(expected & predicted)
    precision = true_positive / len(predicted) if predicted else 1.0
    recall = true_positive / len(expected) if expected else 1.0
    return {"precision": precision, "recall": recall}


def memo_hallucination_rate(claims: list[MemoClaim], fields: dict[str, ExtractedField]) -> float:
    unsupported = sum(1 for claim in claims if not memo_claim_is_supported(claim, fields))
    return unsupported / len(claims) if claims else 0.0


PROMPT_MODEL_REGRESSION = [
    {"iteration": "v1_raw_extraction", "extraction_accuracy": 0.86, "breach_recall": 1.00, "memo_hallucination_rate": 0.18},
    {"iteration": "v2_cited_schema", "extraction_accuracy": 0.96, "breach_recall": 1.00, "memo_hallucination_rate": 0.04},
]
