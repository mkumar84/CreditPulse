import pytest

from creditpulse.covenants import breached_months, load_financials, monitor_covenants
from creditpulse.evals import covenant_precision_recall, extraction_accuracy, load_prompt_model_regression, memo_hallucination_rate
from creditpulse.extraction import extract_from_sources, flatten_extraction_table
from creditpulse.policy import ExtractedField, MemoClaim, final_memo_allowed, render_claim


@pytest.fixture(autouse=True)
def _no_live_anthropic_key(monkeypatch):
    """Keep tests hermetic: exercise the deterministic fallback, never the network."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


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
    from creditpulse.api import FALLBACK_MEMO_MODEL_LABEL, build_contract_payload

    payload = build_contract_payload()
    assert set(payload) == {"extraction", "covenants", "memo", "evals"}
    assert payload["extraction"]["borrower"]["value"] == "Meridian SaaS Co."
    assert payload["covenants"]["breach_months"] == ["2026-07"]
    assert payload["memo"]["model_label"] == FALLBACK_MEMO_MODEL_LABEL
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


def test_rejects_claim_citing_nonexistent_extraction_field():
    fields = {"arr": ExtractedField("arr", 36.5, "monthly_financials.csv:2026-12")}
    unsupported = MemoClaim("Bookings accelerated.", ("bookings",))
    assert render_claim(unsupported, fields).startswith("[NEEDS REVIEW]")


def test_unsupported_claim_is_flagged_needs_review():
    from creditpulse.api import build_memo_payload

    payload = build_memo_payload()
    unsupported_claims = [claim for claim in payload["claims"] if "Pipeline conversion" in claim["text"]]
    assert unsupported_claims
    assert unsupported_claims[0]["rendered_text"] == "[NEEDS REVIEW] Pipeline conversion improved materially."
    assert unsupported_claims[0]["field_names"] == ["pipeline_conversion"]
    assert unsupported_claims[0]["source_note"] == "No source — flagged as needs review"
    assert unsupported_claims[0]["needs_review"] is True


def test_api_cors_defaults_to_creditpulse_live():
    from creditpulse.api import DEFAULT_ALLOWED_ORIGIN

    assert DEFAULT_ALLOWED_ORIGIN == "https://creditpulse.live"


def test_extraction_payload_includes_confidence_and_monthly_series():
    from creditpulse.api import build_extraction_payload

    payload = build_extraction_payload()
    assert payload["borrower"]["citation"]["confidence"] == 0.99
    assert payload["covenants"]["net_burn_multiple_cap"]["citation"]["confidence"] == 0.98
    assert len(payload["monthly_series"]) == 24
    assert payload["monthly_series"][0] == {
        "month": "2025-01",
        "arr_millions": 18.0,
        "mrr_millions": 1.5,
        "churn_pct": 1.8,
    }
    assert payload["monthly_series"][-1]["month"] == "2026-12"


def test_memo_payload_includes_four_sections_and_claim_sources():
    from creditpulse.api import build_memo_payload

    payload = build_memo_payload()
    assert [section["section_name"] for section in payload["sections"]] == [
        "Facility Summary",
        "Operating Performance",
        "Liquidity & Burn",
        "Recommendation",
    ]
    assert len(payload["claims"]) == 8
    sourced_claims = [claim for claim in payload["claims"] if not claim["needs_review"]]
    assert all(claim["sources"] for claim in sourced_claims)


def test_evals_payload_includes_breach_counts_and_field_accuracy():
    from creditpulse.api import build_evals_payload

    payload = build_evals_payload()
    assert payload["breach_counts"] == {
        "true_positive": 1,
        "false_positive": 0,
        "false_negative": 0,
    }
    assert {row["field_name"] for row in payload["field_accuracy"]} >= {
        "ARR",
        "Cash Balance",
        "Burn Multiple",
        "Facility Size",
        "MAC-Style / Committed MRR Interpretation",
    }
    assert payload["missing_ground_truth"] == []


def test_facility_size_cites_the_actual_committed_facility_clause():
    from creditpulse.api import build_evals_payload

    row = next(r for r in build_evals_payload()["field_accuracy"] if r["field_name"] == "Facility Size")
    assert row["citation"] == "loan_agreement.md §1.1"
    assert row["accuracy"] == 1.0


def test_monthly_field_accuracy_is_not_tautological_arr_can_actually_fail():
    """Prove the ARR check compares real values, not a hardcoded 1.0: corrupt one
    month's extracted value and confirm the accuracy score actually drops."""
    from creditpulse.api import _scored_monthly_field
    from creditpulse.covenants import MonthlyFinancial

    financials = [
        MonthlyFinancial("2025-01", 18.0, 1.50, 1.8, 1.20, 22.0, 142, 116, "baseline"),
        MonthlyFinancial("2025-02", 18.7, 1.56, 1.7, 1.22, 21.2, 145, 116, "baseline"),
    ]
    monthly_truth = {
        "months": {
            "2025-01": {"arr_millions": 18.0},
            "2025-02": {"arr_millions": 18.7},
        }
    }
    correct = _scored_monthly_field("ARR", "arr_millions", financials, monthly_truth)
    assert correct["accuracy"] == 1.0

    corrupted_financials = [financials[0], MonthlyFinancial("2025-02", 99.9, 1.56, 1.7, 1.22, 21.2, 145, 116, "baseline")]
    wrong = _scored_monthly_field("ARR", "arr_millions", corrupted_financials, monthly_truth)
    assert wrong["accuracy"] == 0.5


def test_burn_multiple_accuracy_is_not_tautological_can_actually_fail():
    """Prove the burn-multiple check compares real values: a wrong computed
    value must score below 1.0 against the independently re-derived ground truth."""
    from creditpulse.api import _scored_burn_multiple

    truth = {"2026-07": 2.195833}
    correct = _scored_burn_multiple({"2026-07": 2.195833}, truth)
    assert correct["accuracy"] == 1.0

    wrong = _scored_burn_multiple({"2026-07": 0.5}, truth)
    assert wrong["accuracy"] == 0.0


def test_monthly_metrics_ground_truth_matches_live_data_with_zero_discrepancies():
    """Regression guard: the independently-authored ground truth file should
    agree with the live CSV/covenant computation for every one of the 24
    months (and 22 burn-multiple months) — this is what makes the 100% score
    in build_evals_payload() a measured result rather than an assumption."""
    import json

    from creditpulse.api import build_evals_payload
    from creditpulse.covenants import load_financials, monitor_covenants

    monthly_truth = json.loads(open("data/ground_truth/monthly_metrics_answer_key.json").read())
    financials = load_financials("data/synthetic/monthly_financials.csv")
    assert len(monthly_truth["months"]) == len(financials) == 24
    assert len(monthly_truth["burn_multiple"]) == 22

    results = monitor_covenants(financials)
    burn_actual = {r.month: r.computed_value for r in results if r.covenant == "net_burn_multiple_cap"}
    assert set(burn_actual) == set(monthly_truth["burn_multiple"])

    for row in build_evals_payload()["field_accuracy"]:
        if row["field_name"] in {"ARR", "MRR", "Gross Churn %", "Cash Balance", "Burn Multiple"}:
            assert row["accuracy"] == 1.0, row


def test_all_extraction_citations_include_confidence_scores():
    from creditpulse.api import build_extraction_payload

    payload = build_extraction_payload()
    citations = [payload["borrower"]["citation"]]
    citations.extend(field["citation"] for field in payload["covenants"].values())
    citations.extend(field["citation"] for field in payload["latest_month"].values())
    assert citations
    assert all(0.0 <= citation["confidence"] <= 1.0 for citation in citations)


def test_missing_ground_truth_is_empty_after_field_truth_closure():
    from creditpulse.api import build_evals_payload

    assert build_evals_payload()["missing_ground_truth"] == []


def test_memo_payload_falls_back_without_an_anthropic_api_key():
    from creditpulse.api import FALLBACK_MEMO_MODEL_LABEL, build_memo_payload
    from creditpulse.memo_drafter import draft_memo_claims

    fields = flatten_extraction_table("data/synthetic/extraction_table.json")
    assert draft_memo_claims(fields, {"breach_months": []}) is None

    payload = build_memo_payload()
    assert payload["model_label"] == FALLBACK_MEMO_MODEL_LABEL
    assert len(payload["claims"]) == 8


def test_live_drafted_claims_are_still_gated_by_policy(monkeypatch):
    """Even when the Claude API is live, a hallucinated field must not slip through."""
    import creditpulse.api as api

    fake_claims = [
        MemoClaim("Meridian SaaS Co. is the borrower.", ("borrower",)),
        MemoClaim("Pipeline conversion improved materially.", ("pipeline_conversion",)),
    ]
    fake_sections = ["Facility Summary", "Recommendation"]
    monkeypatch.setattr(api, "draft_memo_claims", lambda fields, covenant_payload: (fake_claims, fake_sections))

    payload = api.build_memo_payload()

    assert payload["model_label"] == api.LIVE_MEMO_MODEL_LABEL
    assert len(payload["claims"]) == 2
    supported, unsupported = payload["claims"]
    assert supported["needs_review"] is False
    assert unsupported["needs_review"] is True
    assert unsupported["rendered_text"].startswith("[NEEDS REVIEW]")
    assert payload["sections"][0] == {"section_name": "Facility Summary", "text": "Meridian SaaS Co. is the borrower."}


@pytest.mark.parametrize(
    ("question", "expected_lookup", "expected_value", "citation_fragment"),
    [
        ("what's the current ARR", "current_arr", 36.5, "monthly_financials.csv"),
        ("what's the current MRR", "current_mrr", 3.04, "monthly_financials.csv"),
        ("what's the current cash balance", "current_cash_balance", 10.2, "monthly_financials.csv"),
        ("what's the current NRR", "current_nrr", 110.0, "monthly_financials.csv"),
        ("what's the NRR floor covenant status", "nrr_floor_status", 110.0, "loan_agreement.md §4.4"),
        ("what's the current cash runway", "liquidity_runway_status", 6.8, "loan_agreement.md §4.1"),
        ("what's the current burn multiple", "burn_multiple_status", 0.467, "loan_agreement.md §4.3"),
        ("is the ARR growth floor covenant breached", "arr_growth_floor_status", 29.4326, "loan_agreement.md §4.2"),
        ("what's the committed MRR interpretation", "committed_mrr_interpretation_status", 3.04, "loan_agreement.md §4.5"),
        ("when did the covenant breach happen", "breach_months", ["2026-07"], "loan_agreement.md"),
        (
            "what months are flagged for human review",
            "human_review_months",
            ["2026-04", "2026-05", "2026-06", "2026-12"],
            "loan_agreement.md",
        ),
        ("what's the facility size", "facility_size", 15.0, "loan_agreement.md"),
    ],
)
def test_ask_lookup_returns_correct_cited_value(question, expected_lookup, expected_value, citation_fragment):
    """One case per fixed lookup category: matches the right lookup, returns the
    right value, and carries a citation traceable to the same source used
    elsewhere in the API (never a fabricated or uncited answer)."""
    from creditpulse.api import build_ask_payload

    result = build_ask_payload(question)
    assert result["matched"] is True
    assert result["lookup"] == expected_lookup
    assert result["sources"], "a matched answer must always carry at least one source citation"

    if isinstance(expected_value, float):
        assert result["answer"]["value"] == pytest.approx(expected_value, rel=1e-3)
    else:
        assert result["answer"]["value"] == expected_value

    assert citation_fragment in str(result["sources"][0]["citation"])


@pytest.mark.parametrize(
    "question",
    [
        "what's the CEO's name",
        "what's the weather today",
        "should we approve this loan",
        "",
    ],
)
def test_ask_out_of_scope_question_returns_explicit_not_available(question):
    """The most important behavior to test: an unmatched question must never
    be guessed at — it gets the fixed not-available response, verbatim."""
    from creditpulse.api import build_ask_payload
    from creditpulse.ask import NOT_AVAILABLE_MESSAGE

    result = build_ask_payload(question)
    assert result["matched"] is False
    assert result["lookup"] is None
    assert result["answer"] is None
    assert result["sources"] == []
    assert result["message"] == NOT_AVAILABLE_MESSAGE


def test_ask_answer_carries_deterministic_value_alongside_phrased_text():
    """Requirement: even the human-readable text is backed by a returned
    deterministic value + citation the UI can display side by side."""
    from creditpulse.api import build_ask_payload

    result = build_ask_payload("what's the current burn multiple")
    assert result["text"] == "As of 2026-12, the net burn multiple was 0.467x against a 1.5x threshold (in compliance)."
    assert result["answer"]["value"] == pytest.approx(0.467, rel=1e-3)
    assert result["answer"]["breached"] is False
    assert result["sources"] == [{"field": "net_burn_multiple_cap", "citation": "loan_agreement.md §4.3"}]


def test_ask_facility_size_cites_the_actual_facility_clause_not_the_liquidity_covenant():
    """Regression guard for the earlier Facility Size mislabeling: /ask must cite
    §1.1 (the real committed facility clause), never §4.1 (the liquidity covenant)."""
    from creditpulse.api import build_ask_payload

    citation = build_ask_payload("what's the facility size")["sources"][0]["citation"]
    assert citation["document"] == "loan_agreement.md"
    assert citation["section"] == "1.1"
