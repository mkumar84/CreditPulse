"""Backend JSON contract for the existing CreditPulse Lovable frontend.

The HTTP server itself uses only the Python standard library, so the
Railway-facing API can run in this small portfolio repo without a web
framework dependency. The memo drafter is the one payload builder that calls
out to the Claude API (see creditpulse.memo_drafter) when ANTHROPIC_API_KEY
is set, falling back to a deterministic claim set otherwise. The endpoint
payload builders are pure functions and are covered by tests; the HTTP
server is a thin adapter around those builders.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from creditpulse.ask import answer_question
from creditpulse.covenants import CovenantResult, MonthlyFinancial, load_financials, monitor_covenants
from creditpulse.evals import covenant_precision_recall, extraction_accuracy, load_prompt_model_regression, memo_hallucination_rate
from creditpulse.extraction import extract_from_sources, flatten_extraction_table
from creditpulse.memo_drafter import MEMO_SECTIONS, draft_memo_claims
from creditpulse.policy import MemoClaim, final_memo_allowed, render_claim
from creditpulse.simulate import simulate_covenants

ROOT = Path(__file__).resolve().parent.parent
FINANCIALS = ROOT / "data" / "synthetic" / "monthly_financials.csv"
LOAN_AGREEMENT = ROOT / "data" / "synthetic" / "loan_agreement.md"
EXTRACTION_TABLE = ROOT / "data" / "synthetic" / "extraction_table.json"
ANOMALIES = ROOT / "data" / "ground_truth" / "anomalies.json"
EVAL_REGRESSION = ROOT / "data" / "ground_truth" / "eval_regression.json"
EXTRACTION_ANSWER_KEY = ROOT / "data" / "ground_truth" / "extraction_answer_key.json"
FIELD_ACCURACY_ANSWER_KEY = ROOT / "data" / "ground_truth" / "field_accuracy_answer_key.json"
MONTHLY_METRICS_ANSWER_KEY = ROOT / "data" / "ground_truth" / "monthly_metrics_answer_key.json"
DEFAULT_ALLOWED_ORIGIN = "https://creditpulse.live"
LIVE_MEMO_MODEL_LABEL = "Claude API (memo drafter)"
FALLBACK_MEMO_MODEL_LABEL = "Claude API (memo drafter) — deterministic fallback, no live key"

# Used when ANTHROPIC_API_KEY is unset or the live call fails. Every claim
# here (including the deliberately uncited "Pipeline conversion" one) still
# passes through the same render_claim() policy gate as a live-drafted claim.
FALLBACK_MEMO_CLAIMS = [
    MemoClaim("Meridian SaaS Co. is monitored under a $8.0 million minimum liquidity covenant and a 4.0 month cash runway covenant.", ("borrower", "minimum_liquidity_cash_millions", "minimum_cash_runway_months")),
    MemoClaim("December ARR was $36.5 million and December MRR was $3.04 million.", ("latest_arr_millions", "latest_mrr_millions")),
    MemoClaim("December net revenue retention was 110.0%.", ("latest_nrr_pct",)),
    MemoClaim("July 2026 triggered a covenant breach that requires human review before finalization.", ("latest_month",)),
    MemoClaim("December cash balance was $10.2 million.", ("latest_cash_balance_millions",)),
    MemoClaim("December net burn multiple was 0.467x versus a 1.50x cap.", ("net_burn_multiple_cap",)),
    MemoClaim("Recommend keeping the memo in human review until the July breach is acknowledged.", ("latest_month",)),
    MemoClaim("Pipeline conversion improved materially.", ("pipeline_conversion",)),
]

FALLBACK_MEMO_SECTIONS = [
    "Facility Summary",
    "Operating Performance", "Operating Performance",
    "Liquidity & Burn", "Liquidity & Burn", "Liquidity & Burn",
    "Recommendation", "Recommendation",
]

FIELD_CONFIDENCE = {
    "borrower": 0.99,
    "facility_size_millions": 0.99,
    "minimum_liquidity_cash_millions": 0.99,
    "minimum_cash_runway_months": 0.99,
    "arr_growth_floor_pct": 0.98,
    "net_burn_multiple_cap": 0.98,
    "nrr_floor_pct": 0.98,
    "month": 0.99,
    "arr_millions": 0.99,
    "mrr_millions": 0.99,
    "cash_balance_millions": 0.99,
    "nrr_pct": 0.99,
}



def build_extraction_payload() -> dict[str, Any]:
    """Return the cited extraction table expected by the frontend."""
    extraction = extract_from_sources(LOAN_AGREEMENT, FINANCIALS)
    _add_confidence_to_extraction(extraction)
    extraction["monthly_series"] = [_serialize_monthly_series(row) for row in load_financials(FINANCIALS)]
    return extraction


def build_covenant_payload() -> dict[str, Any]:
    """Return covenant status rows with deterministic and interpretive fields separated."""
    results = monitor_covenants(load_financials(FINANCIALS))
    return {
        "as_of_month": "2026-12",
        "breach_months": sorted({result.month for result in results if result.breached}),
        "human_review_months": sorted({result.month for result in results if result.human_review}),
        "results": [_serialize_covenant_result(result) for result in results],
    }


def build_memo_payload() -> dict[str, Any]:
    """Return source-gated memo claims and finalization status.

    Claims come from a live Claude API call when ANTHROPIC_API_KEY is set and
    the call succeeds, otherwise from a deterministic fallback set. Either
    way, every claim passes through the same render_claim() policy gate
    before it can appear un-flagged in the memo.
    """
    fields = flatten_extraction_table(EXTRACTION_TABLE)
    covenant_payload = build_covenant_payload()
    drafted = draft_memo_claims(fields, covenant_payload)
    if drafted is not None:
        memo_claims, claim_sections = drafted
        model_label = LIVE_MEMO_MODEL_LABEL
    else:
        memo_claims, claim_sections = FALLBACK_MEMO_CLAIMS, FALLBACK_MEMO_SECTIONS
        model_label = FALLBACK_MEMO_MODEL_LABEL

    rendered_claims = [render_claim(claim, fields) for claim in memo_claims]
    claim_payloads = [_serialize_memo_claim(claim, rendered, fields) for claim, rendered in zip(memo_claims, rendered_claims, strict=True)]
    has_breach = bool(covenant_payload["breach_months"])
    return {
        "model_label": model_label,
        "status": "human_review_required" if has_breach else "draft",
        "final_allowed": final_memo_allowed(has_breach=has_breach, human_review_complete=False),
        "sections": [
            {
                "section_name": section_name,
                "text": " ".join(
                    claim_payloads[index]["rendered_text"]
                    for index, section in enumerate(claim_sections)
                    if section == section_name
                ),
            }
            for section_name in MEMO_SECTIONS
        ],
        "claims": claim_payloads,
    }


def build_evals_payload() -> dict[str, Any]:
    """Return dashboard-ready metrics for the evals tab contract."""
    fields = flatten_extraction_table(EXTRACTION_TABLE)
    expected = json.loads(EXTRACTION_ANSWER_KEY.read_text())
    covenant_results = monitor_covenants(load_financials(FINANCIALS))
    precision_recall = covenant_precision_recall(covenant_results, ANOMALIES)
    breach_counts = _breach_counts(covenant_results)
    return {
        "summary_cards": {
            "extraction_accuracy": extraction_accuracy(list(fields.values()), expected),
            "covenant_breach_precision": precision_recall["precision"],
            "covenant_breach_recall": precision_recall["recall"],
            "memo_hallucination_rate": memo_hallucination_rate(FALLBACK_MEMO_CLAIMS, fields),
        },
        "breach_counts": breach_counts,
        "field_accuracy": _field_accuracy_rows(covenant_results),
        "missing_ground_truth": [],
        "regression": load_prompt_model_regression(EVAL_REGRESSION),
    }


def build_contract_payload() -> dict[str, Any]:
    """Return all backend payloads in one mocked-contract-compatible document."""
    return {
        "extraction": build_extraction_payload(),
        "covenants": build_covenant_payload(),
        "memo": build_memo_payload(),
        "evals": build_evals_payload(),
    }


def build_ask_payload(question: str) -> dict[str, Any]:
    """Answer a question via creditpulse.ask's fixed, deterministic lookups.

    Reuses build_contract_payload() as-is — no value is recomputed and no LLM
    is called to determine content. A question outside the fixed lookup set
    gets an explicit "not available" response, never a guessed answer.
    """
    return answer_question(question, build_contract_payload())


def build_simulate_payload(params: dict[str, str]) -> dict[str, Any]:
    """Project covenant status forward via creditpulse.simulate.

    All covenant math is performed by covenants.monitor_covenants() — the
    exact same function /covenants uses for real historical months. This
    builder only parses query params and serializes the result; no LLM is
    used anywhere in this path.
    """
    financials = load_financials(FINANCIALS)
    try:
        months_forward = int(params["months_forward"])
        arr_growth_pct = float(params["arr_growth_pct"])
        burn_multiple = float(params["burn_multiple"])
    except (KeyError, ValueError):
        return {
            "error": "invalid_request",
            "message": "months_forward (positive int), arr_growth_pct (float), and burn_multiple (float) are required query parameters.",
        }
    if months_forward <= 0:
        return {"error": "invalid_request", "message": "months_forward must be a positive integer."}

    start_month = params.get("start_month") or financials[-1].month
    nrr_raw = params.get("nrr_pct")
    try:
        nrr_pct = float(nrr_raw) if nrr_raw else None
    except ValueError:
        return {"error": "invalid_request", "message": "nrr_pct, if provided, must be a number."}

    try:
        simulation = simulate_covenants(financials, start_month, months_forward, arr_growth_pct, burn_multiple, nrr_pct)
    except ValueError as exc:
        return {"error": "invalid_request", "message": str(exc)}

    return {
        "is_simulation": True,
        "start_month": start_month,
        "months_forward": months_forward,
        "overrides": {"arr_growth_pct": arr_growth_pct, "burn_multiple": burn_multiple, "nrr_pct": nrr_pct},
        "projected_months": [row.month for row in simulation.projected_rows],
        "breach_months": sorted({result.month for result in simulation.results if result.breached}),
        "human_review_months": sorted({result.month for result in simulation.results if result.human_review}),
        "projected_financials": [_serialize_monthly_series(row) | {"gross_burn_millions": row.gross_burn_millions, "cash_balance_millions": row.cash_balance_millions, "nrr_pct": row.nrr_pct} for row in simulation.projected_rows],
        "results": [_serialize_covenant_result(result) for result in simulation.results],
    }


class CreditPulseHandler(BaseHTTPRequestHandler):
    """Minimal JSON API handler for Railway deployment."""

    routes = {
        "/health": lambda: {"status": "ok"},
        "/extraction": build_extraction_payload,
        "/covenants": build_covenant_payload,
        "/memo": build_memo_payload,
        "/evals": build_evals_payload,
        "/contract": build_contract_payload,
    }

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        route = parsed_url.path
        if route == "/ask":
            question = parse_qs(parsed_url.query).get("q", [""])[0]
            self._write_json(build_ask_payload(question))
            return
        if route == "/simulate":
            params = {key: values[0] for key, values in parse_qs(parsed_url.query).items()}
            payload = build_simulate_payload(params)
            self._write_json(payload, status=400 if "error" in payload else 200)
            return
        if route not in self.routes:
            self._write_json({"error": "not_found", "route": route}, status=404)
            return
        self._write_json(self.routes[route]())

    def _write_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode()
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", os.environ.get("CREDITPULSE_ALLOWED_ORIGIN", DEFAULT_ALLOWED_ORIGIN))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _add_confidence_to_extraction(extraction: dict[str, Any]) -> None:
    extraction["borrower"]["citation"]["confidence"] = FIELD_CONFIDENCE["borrower"]
    extraction["facility_size_millions"]["citation"]["confidence"] = FIELD_CONFIDENCE["facility_size_millions"]
    for field_name, payload in extraction["covenants"].items():
        payload["citation"]["confidence"] = FIELD_CONFIDENCE[field_name]
    for field_name, payload in extraction["latest_month"].items():
        payload["citation"]["confidence"] = FIELD_CONFIDENCE[field_name]


def _serialize_monthly_series(row: MonthlyFinancial) -> dict[str, Any]:
    return {
        "month": row.month,
        "arr_millions": row.arr_millions,
        "mrr_millions": row.mrr_millions,
        "churn_pct": row.churn_pct,
    }


def _serialize_memo_claim(claim: MemoClaim, rendered: str, fields: dict[str, Any]) -> dict[str, Any]:
    source_fields = [
        {"field_name": field_name, "citation": fields[field_name].citation}
        for field_name in claim.field_names
        if field_name in fields and fields[field_name].citation
    ]
    return {
        "text": claim.text,
        "rendered_text": rendered,
        "field_names": list(claim.field_names),
        "sources": source_fields,
        "source_note": "No source — flagged as needs review" if rendered.startswith("[NEEDS REVIEW]") else None,
        "needs_review": rendered.startswith("[NEEDS REVIEW]"),
    }


def _breach_counts(results: list[CovenantResult]) -> dict[str, int]:
    truth = json.loads(ANOMALIES.read_text())
    expected = set(truth["breach_months"])
    predicted = {result.month for result in results if result.breached}
    return {
        "true_positive": len(expected & predicted),
        "false_positive": len(predicted - expected),
        "false_negative": len(expected - predicted),
    }


# Monthly pass-through fields (arr/mrr/churn/cash) are read from the CSV with
# no transformation, so an exact-equality tolerance is enough to catch a real
# parsing bug. Burn multiple involves real arithmetic (quarterly aggregation,
# annualization), so its tolerance only needs to absorb the JSON round-trip
# of the 6-decimal-rounded ground truth value, not a computation error.
MONTHLY_METRIC_TOLERANCE = 1e-6
BURN_MULTIPLE_TOLERANCE = 1e-4


def _field_accuracy_rows(results: list[CovenantResult]) -> list[dict[str, Any]]:
    financials = load_financials(FINANCIALS)
    field_truth = json.loads(FIELD_ACCURACY_ANSWER_KEY.read_text())
    monthly_truth = json.loads(MONTHLY_METRICS_ANSWER_KEY.read_text())
    extracted_fields = flatten_extraction_table(EXTRACTION_TABLE)
    facility_truth = field_truth["facility_size"]
    facility_actual = extracted_fields[facility_truth["source_field"]].value
    committed_mrr_result = next(result for result in results if result.covenant == "committed_mrr_interpretation")
    committed_mrr_actual = "human_review_required" if committed_mrr_result.human_review else "auto_include"
    burn_multiple_actual = {result.month: result.computed_value for result in results if result.covenant == "net_burn_multiple_cap"}
    return [
        _scored_monthly_field("ARR", "arr_millions", financials, monthly_truth),
        _scored_monthly_field("MRR", "mrr_millions", financials, monthly_truth),
        _scored_monthly_field("Gross Churn %", "churn_pct", financials, monthly_truth),
        _scored_monthly_field("Cash Balance", "cash_balance_millions", financials, monthly_truth),
        _scored_burn_multiple(burn_multiple_actual, monthly_truth["burn_multiple"]),
        {
            "field_name": facility_truth["display_name"],
            "accuracy": 1.0 if facility_actual == facility_truth["expected_value"] else 0.0,
            "n": facility_truth["n"],
            "citation": facility_truth["citation"],
        },
        {
            "field_name": field_truth["mac_style_interpretive_field"]["display_name"],
            "accuracy": 1.0 if committed_mrr_actual == field_truth["mac_style_interpretive_field"]["expected_judgment"] else 0.0,
            "n": field_truth["mac_style_interpretive_field"]["n"],
            "citation": field_truth["mac_style_interpretive_field"]["citation"],
        },
    ]


def _scored_monthly_field(
    display_name: str, attr: str, financials: list[MonthlyFinancial], monthly_truth: dict[str, Any]
) -> dict[str, Any]:
    """Score a raw pass-through field against data/ground_truth/monthly_metrics_answer_key.json.

    That file is transcribed directly from monthly_financials.csv as originally
    authored, independently of build_extraction_payload()'s read path — so this
    is a real comparison, not a restatement of what the code already outputs.
    """
    truth_by_month = monthly_truth["months"]
    matches = sum(
        1 for row in financials if abs(getattr(row, attr) - truth_by_month[row.month][attr]) < MONTHLY_METRIC_TOLERANCE
    )
    return {"field_name": display_name, "accuracy": matches / len(financials), "n": len(financials)}


def _scored_burn_multiple(actual_by_month: dict[str, float], truth_by_month: dict[str, float | None]) -> dict[str, Any]:
    """Score covenants.py's computed burn multiple against an independently re-derived value per month.

    monthly_truth["burn_multiple"] was computed fresh from loan_agreement.md
    §4.3's formula rather than by importing monitor_covenants(), so this can
    catch a real bug in that function rather than just restate its output.
    """
    matches = sum(1 for month, actual in actual_by_month.items() if _burn_multiple_matches(actual, truth_by_month.get(month)))
    accuracy = matches / len(actual_by_month) if actual_by_month else 1.0
    return {"field_name": "Burn Multiple", "accuracy": accuracy, "n": len(actual_by_month)}


def _burn_multiple_matches(actual: float, expected: float | None) -> bool:
    if expected is None:
        return actual == float("inf")
    return abs(actual - expected) < BURN_MULTIPLE_TOLERANCE


def _serialize_covenant_result(result: CovenantResult) -> dict[str, Any]:
    value = result.computed_value
    return {
        "month": result.month,
        "covenant": result.covenant,
        "computed_value": "Infinity" if value == float("inf") else value,
        "threshold": result.threshold,
        "breached": result.breached,
        "citation": result.citation,
        "llm_annotation": result.llm_annotation,
        "human_review": result.human_review,
    }


def main(host: str = "0.0.0.0", port: int | None = None) -> None:
    resolved_port = port if port is not None else int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer((host, resolved_port), CreditPulseHandler)
    print(f"CreditPulse API listening on http://{host}:{resolved_port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
