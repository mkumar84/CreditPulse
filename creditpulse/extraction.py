"""Utilities for working with cited extraction tables.

The extraction layer is intentionally deterministic for this portfolio demo: it
turns the version-controlled synthetic source files into the same structured
shape an LLM extraction agent would be required to emit, including provenance
for every field. Ambiguous legal interpretation remains outside this parser.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from creditpulse.policy import ExtractedField

MoneyOrPercent = float


def citation_to_text(citation: dict[str, Any]) -> str:
    """Render a structured citation as compact document provenance text."""
    document = citation["document"]
    if "section" in citation:
        return f"{document} §{citation['section']}"
    if "line" in citation:
        return f"{document} line {citation['line']}"
    if "row" in citation:
        return f"{document} row {citation['row']}"
    return document


def flatten_extraction_table(path: str | Path) -> dict[str, ExtractedField]:
    """Flatten the nested extraction fixture into policy-checkable fields."""
    table = json.loads(Path(path).read_text())
    fields: dict[str, ExtractedField] = {
        "borrower": ExtractedField("borrower", table["borrower"]["value"], citation_to_text(table["borrower"]["citation"])),
        "facility_size_millions": ExtractedField(
            "facility_size_millions",
            table["facility_size_millions"]["value"],
            citation_to_text(table["facility_size_millions"]["citation"]),
        ),
    }
    for name, payload in table["covenants"].items():
        fields[name] = ExtractedField(name, payload["value"], citation_to_text(payload["citation"]))
    for name, payload in table["latest_month"].items():
        field_name = f"latest_{name}" if name != "month" else "latest_month"
        fields[field_name] = ExtractedField(
            field_name,
            payload["value"],
            citation_to_text(payload["citation"]),
        )
    return fields


def extract_from_sources(loan_agreement_path: str | Path, monthly_financials_path: str | Path) -> dict[str, Any]:
    """Extract cited borrower, covenant, and latest-period fields from sources.

    This function is the bounded extraction-agent scaffold for the current build
    step. It parses the existing static fixtures and emits structured JSON with
    a citation on every field; it does not regenerate source data.
    """
    loan_path = Path(loan_agreement_path)
    financials_path = Path(monthly_financials_path)
    loan_lines = loan_path.read_text().splitlines()
    borrower = _extract_borrower(loan_path.name, loan_lines)
    covenants = _extract_covenants(loan_path.name, loan_lines)
    latest_month = _extract_latest_month(financials_path)
    return {"borrower": borrower, "covenants": covenants, "latest_month": latest_month}


def write_extraction_table(extraction: dict[str, Any], output_path: str | Path) -> None:
    """Persist an extraction table as stable, human-readable JSON."""
    Path(output_path).write_text(json.dumps(extraction, indent=2) + "\n")


def _extract_borrower(document: str, loan_lines: list[str]) -> dict[str, Any]:
    title = loan_lines[0]
    borrower = title.removeprefix("# ").removesuffix(" Loan Agreement Excerpt")
    return {"value": borrower, "citation": {"document": document, "line": 1}}


def _extract_covenants(document: str, loan_lines: list[str]) -> dict[str, Any]:
    sections = _section_bodies(loan_lines)
    liquidity = sections["4.1"]
    arr_growth = sections["4.2"]
    burn_multiple = sections["4.3"]
    nrr = sections["4.4"]
    return {
        "minimum_liquidity_cash_millions": {
            "value": _first_number_after(r"at least \$(\d+(?:\.\d+)?) million", liquidity["body"]),
            "citation": {"document": document, "section": "4.1", "line": liquidity["line"]},
        },
        "minimum_cash_runway_months": {
            "value": _first_number_after(r"at least (\d+(?:\.\d+)?) months", liquidity["body"]),
            "citation": {"document": document, "section": "4.1", "line": liquidity["line"]},
        },
        "arr_growth_floor_pct": {
            "value": _first_number_after(r"at least (\d+(?:\.\d+)?)%", arr_growth["body"]),
            "citation": {"document": document, "section": "4.2", "line": arr_growth["line"]},
        },
        "net_burn_multiple_cap": {
            "value": _first_number_after(r"no greater than (\d+(?:\.\d+)?)x", burn_multiple["body"]),
            "citation": {"document": document, "section": "4.3", "line": burn_multiple["line"]},
        },
        "nrr_floor_pct": {
            "value": _first_number_after(r"at least (\d+(?:\.\d+)?)%", nrr["body"]),
            "citation": {"document": document, "section": "4.4", "line": nrr["line"]},
        },
    }


def _extract_latest_month(financials_path: Path) -> dict[str, Any]:
    with financials_path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    latest = rows[-1]
    csv_row_number = len(rows) + 1
    citation = {"document": financials_path.name, "row": csv_row_number}
    return {
        "month": {"value": latest["month"], "citation": citation},
        "arr_millions": {"value": float(latest["arr_millions"]), "citation": citation},
        "mrr_millions": {"value": float(latest["mrr_millions"]), "citation": citation},
        "cash_balance_millions": {"value": float(latest["cash_balance_millions"]), "citation": citation},
        "nrr_pct": {"value": float(latest["nrr_pct"]), "citation": citation},
    }


def _section_bodies(lines: list[str]) -> dict[str, dict[str, str | int]]:
    sections: dict[str, dict[str, str | int]] = {}
    for index, line in enumerate(lines):
        match = re.match(r"## Section (\d+\.\d+)", line)
        if not match:
            continue
        body = lines[index + 1] if index + 1 < len(lines) else ""
        sections[match.group(1)] = {"body": body, "line": index + 2}
    return sections


def _first_number_after(pattern: str, text: str) -> MoneyOrPercent:
    match = re.search(pattern, text)
    if not match:
        raise ValueError(f"Unable to extract numeric covenant from: {text}")
    return float(match.group(1))
