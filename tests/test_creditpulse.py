from creditpulse.covenants import breached_months, load_financials, monitor_covenants
from creditpulse.evals import covenant_precision_recall, extraction_accuracy, load_prompt_model_regression, memo_hallucination_rate
from creditpulse.extraction import extract_from_sources, flatten_extraction_table
from creditpulse.policy import ExtractedField, MemoClaim, final_memo_allowed, render_claim


def test_covenant_monitor_flags_month_19_breach_and_ambiguous_edge_case():
    results = monitor_covenants(load_financials("data/synthetic/monthly_financials.csv"))
    assert "2026-07" in breached_months(results)
    assert any(result.month == "2026-12" and result.human_review for result in results)


def test_covenant_eval_precision_recall_uses_ground_truth():
    results = monitor_covenants(load_financials("data/synthetic/monthly_financials.csv"))
    metrics = covenant_precision_recall(results, "data/ground_truth/anomalies.json")
    assert metrics["recall"] == 1.0
    assert metrics["precision"] == 1.0


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


def test_extraction_fixture_is_cited_and_scores_against_answer_key():
    fields = flatten_extraction_table("data/synthetic/extraction_table.json")
    expected = {
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
    assert extraction_accuracy(list(fields.values()), expected) == 1.0


def test_regression_metrics_are_chart_ready_for_two_iterations():
    regression = load_prompt_model_regression("data/ground_truth/eval_regression.json")
    assert [row["iteration"] for row in regression] == [
        "v1_raw_extraction",
        "v2_cited_schema_policy_gates",
    ]
    assert regression[-1]["memo_hallucination_rate"] < regression[0]["memo_hallucination_rate"]


def test_extraction_agent_parses_sources_with_citations():
    extraction = extract_from_sources(
        "data/synthetic/loan_agreement.md",
        "data/synthetic/monthly_financials.csv",
    )
    assert extraction["borrower"]["value"] == "Meridian SaaS Co."
    assert extraction["borrower"]["citation"] == {"document": "loan_agreement.md", "line": 1}
    assert extraction["covenants"]["arr_growth_floor_pct"]["value"] == 20.0
    assert extraction["covenants"]["net_burn_multiple_cap"]["citation"]["section"] == "4.3"
    assert extraction["latest_month"]["month"]["value"] == "2026-12"
    assert extraction["latest_month"]["arr_millions"]["citation"] == {
        "document": "monthly_financials.csv",
        "row": 25,
    }


def test_api_contract_payload_exposes_frontend_sections():
    from creditpulse.api import build_contract_payload

    payload = build_contract_payload()
    assert set(payload) == {"extraction", "covenants", "memo", "evals"}
    assert payload["extraction"]["borrower"]["value"] == "Meridian SaaS Co."
    assert payload["covenants"]["breach_months"] == ["2026-07"]
    assert payload["memo"]["status"] == "human_review_required"
    assert payload["evals"]["summary_cards"]["covenant_breach_precision"] == 1.0


def test_api_payload_keeps_computed_values_separate_from_annotations():
    from creditpulse.api import build_covenant_payload

    payload = build_covenant_payload()
    restatement_rows = [
        row for row in payload["results"] if row["human_review"] and row["covenant"] == "net_burn_multiple_cap"
    ]
    assert restatement_rows
    assert all("computed_value" in row and "llm_annotation" in row for row in restatement_rows)
