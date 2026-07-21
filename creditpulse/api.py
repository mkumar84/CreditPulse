"""Backend JSON contract for the existing CreditPulse Lovable frontend.

This module deliberately uses the Python standard library so the Railway-facing
API can run in this small portfolio repo without adding framework dependencies.
The endpoint payload builders are pure functions and are covered by tests; the
HTTP server is a thin adapter around those builders.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from creditpulse.covenants import CovenantResult, load_financials, monitor_covenants
from creditpulse.evals import covenant_precision_recall, extraction_accuracy, load_prompt_model_regression, memo_hallucination_rate
from creditpulse.extraction import extract_from_sources, flatten_extraction_table
from creditpulse.policy import MemoClaim, final_memo_allowed, render_claim

ROOT = Path(__file__).resolve().parent.parent
FINANCIALS = ROOT / "data" / "synthetic" / "monthly_financials.csv"
LOAN_AGREEMENT = ROOT / "data" / "synthetic" / "loan_agreement.md"
EXTRACTION_TABLE = ROOT / "data" / "synthetic" / "extraction_table.json"
ANOMALIES = ROOT / "data" / "ground_truth" / "anomalies.json"
EVAL_REGRESSION = ROOT / "data" / "ground_truth" / "eval_regression.json"
EXTRACTION_ANSWER_KEY = ROOT / "data" / "ground_truth" / "extraction_answer_key.json"

MEMO_CLAIMS = [
    MemoClaim("December ARR was $36.5 million.", ("latest_arr_millions",)),
    MemoClaim("December cash balance was $10.2 million.", ("latest_cash_balance_millions",)),
    MemoClaim("Pipeline conversion improved materially.", ("pipeline_conversion",)),
]


def build_extraction_payload() -> dict[str, Any]:
    """Return the cited extraction table expected by the frontend."""
    return extract_from_sources(LOAN_AGREEMENT, FINANCIALS)


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
    """Return source-gated memo claims and finalization status."""
    fields = flatten_extraction_table(EXTRACTION_TABLE)
    covenant_payload = build_covenant_payload()
    rendered_claims = [render_claim(claim, fields) for claim in MEMO_CLAIMS]
    has_breach = bool(covenant_payload["breach_months"])
    return {
        "status": "human_review_required" if has_breach else "draft",
        "final_allowed": final_memo_allowed(has_breach=has_breach, human_review_complete=False),
        "claims": [
            {
                "text": claim.text,
                "rendered_text": rendered,
                "field_names": list(claim.field_names),
                "needs_review": rendered.startswith("[NEEDS REVIEW]"),
            }
            for claim, rendered in zip(MEMO_CLAIMS, rendered_claims, strict=True)
        ],
    }


def build_evals_payload() -> dict[str, Any]:
    """Return dashboard-ready metrics for the evals tab contract."""
    fields = flatten_extraction_table(EXTRACTION_TABLE)
    expected = json.loads(EXTRACTION_ANSWER_KEY.read_text())
    covenant_results = monitor_covenants(load_financials(FINANCIALS))
    precision_recall = covenant_precision_recall(covenant_results, ANOMALIES)
    return {
        "summary_cards": {
            "extraction_accuracy": extraction_accuracy(list(fields.values()), expected),
            "covenant_breach_precision": precision_recall["precision"],
            "covenant_breach_recall": precision_recall["recall"],
            "memo_hallucination_rate": memo_hallucination_rate(MEMO_CLAIMS, fields),
        },
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
        route = self.path.split("?", 1)[0]
        if route not in self.routes:
            self._write_json({"error": "not_found", "route": route}, status=404)
            return
        self._write_json(self.routes[route]())

    def _write_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode()
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


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
