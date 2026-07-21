"""Run the static CreditPulse demo metrics."""

from __future__ import annotations

from creditpulse.covenants import load_financials, monitor_covenants
from creditpulse.evals import covenant_precision_recall, extraction_accuracy, load_prompt_model_regression, memo_hallucination_rate
from creditpulse.extraction import flatten_extraction_table
from creditpulse.policy import MemoClaim, render_claim


FINANCIALS = "data/synthetic/monthly_financials.csv"
GROUND_TRUTH = "data/ground_truth/anomalies.json"
EXTRACTION_TABLE = "data/synthetic/extraction_table.json"
EXTRACTION_ANSWER_KEY = {
    "borrower": "Meridian SaaS Co.",
    "minimum_liquidity_cash_millions": 8.0,
    "minimum_cash_runway_months": 4.0,
    "arr_growth_floor_pct": 20.0,
    "net_burn_multiple_cap": 1.5,
    "nrr_floor_pct": 100.0,
    "latest_month": "2026-12",
    "latest_arr_millions": 36.5,
    "latest_cash_balance_millions": 10.2,
    "latest_nrr_pct": 110.0,
}
REGRESSION = "data/ground_truth/eval_regression.json"


def main() -> None:
    financials = load_financials(FINANCIALS)
    covenant_results = monitor_covenants(financials)
    fields = flatten_extraction_table(EXTRACTION_TABLE)
    claims = [
        MemoClaim("December ARR was $36.5 million.", ("latest_arr_millions",)),
        MemoClaim("Pipeline conversion improved materially.", ("pipeline_conversion",)),
    ]

    print("CreditPulse demo metrics")
    print(f"Extraction accuracy: {extraction_accuracy(list(fields.values()), EXTRACTION_ANSWER_KEY):.0%}")
    print(f"Covenant precision/recall: {covenant_precision_recall(covenant_results, GROUND_TRUTH)}")
    print(f"Memo hallucination rate: {memo_hallucination_rate(claims, fields):.0%}")
    print("Rendered memo claims:")
    for claim in claims:
        print(f"- {render_claim(claim, fields)}")
    print(f"Regression iterations: {load_prompt_model_regression(REGRESSION)}")


if __name__ == "__main__":
    main()
