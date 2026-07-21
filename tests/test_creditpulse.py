from creditpulse.covenants import breached_months, load_financials, monitor_covenants
from creditpulse.evals import covenant_precision_recall, memo_hallucination_rate
from creditpulse.policy import ExtractedField, MemoClaim, final_memo_allowed, render_claim


def test_covenant_monitor_flags_month_19_breach_and_ambiguous_edge_case():
    results = monitor_covenants(load_financials("data/synthetic/monthly_financials.csv"))
    assert "2026-07" in breached_months(results)
    assert any(result.month == "2026-12" and result.human_review for result in results)


def test_covenant_eval_precision_recall_uses_ground_truth():
    results = monitor_covenants(load_financials("data/synthetic/monthly_financials.csv"))
    metrics = covenant_precision_recall(results, "data/ground_truth/anomalies.json")
    assert metrics["recall"] == 1.0
    assert metrics["precision"] > 0


def test_policy_gates_render_unsupported_claims_for_review():
    fields = {"arr": ExtractedField("arr", 36.5, "monthly_financials.csv:2026-12")}
    supported = MemoClaim("ARR was cited.", ("arr",))
    unsupported = MemoClaim("Bookings accelerated.", ("bookings",))
    assert render_claim(supported, fields) == "ARR was cited."
    assert render_claim(unsupported, fields).startswith("[NEEDS REVIEW]")
    assert memo_hallucination_rate([supported, unsupported], fields) == 0.5


def test_breach_requires_human_review_before_final_memo():
    assert not final_memo_allowed(has_breach=True, human_review_complete=False)
    assert final_memo_allowed(has_breach=True, human_review_complete=True)
