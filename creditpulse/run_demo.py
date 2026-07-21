"""Run the static CreditPulse demo metrics."""

from __future__ import annotations

from creditpulse.covenants import load_financials, monitor_covenants
from creditpulse.evals import PROMPT_MODEL_REGRESSION, covenant_precision_recall, extraction_accuracy, memo_hallucination_rate
from creditpulse.policy import ExtractedField, MemoClaim, render_claim


FINANCIALS = "data/synthetic/monthly_financials.csv"
GROUND_TRUTH = "data/ground_truth/anomalies.json"


def main() -> None:
    financials = load_financials(FINANCIALS)
    results = monitor_covenants(financials)
    latest = financials[-1]
    fields = {
        "arr_millions": ExtractedField("arr_millions", latest.arr_millions, "monthly_financials.csv:2026-12"),
        "nrr_pct": ExtractedField("nrr_pct", latest.nrr_pct, "monthly_financials.csv:2026-12"),
    }
    claims = [
        MemoClaim("December ARR was $36.5 million.", ("arr_millions",)),
        MemoClaim("Pipeline conversion improved materially.", ("pipeline_conversion",)),
    ]
    expected = {"arr_millions": 36.5, "nrr_pct": 110.0}

    print("CreditPulse demo metrics")
    print(f"Extraction accuracy: {extraction_accuracy(list(fields.values()), expected):.0%}")
    print(f"Covenant precision/recall: {covenant_precision_recall(results, GROUND_TRUTH)}")
    print(f"Memo hallucination rate: {memo_hallucination_rate(claims, fields):.0%}")
    print("Rendered memo claims:")
    for claim in claims:
        print(f"- {render_claim(claim, fields)}")
    print(f"Regression iterations: {PROMPT_MODEL_REGRESSION}")


if __name__ == "__main__":
    main()
