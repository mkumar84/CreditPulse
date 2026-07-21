"""Deterministic covenant calculations for Meridian SaaS Co."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MonthlyFinancial:
    month: str
    arr_millions: float
    mrr_millions: float
    churn_pct: float
    gross_burn_millions: float
    cash_balance_millions: float
    headcount: int
    nrr_pct: float
    notes: str


@dataclass(frozen=True)
class CovenantResult:
    month: str
    covenant: str
    computed_value: float
    threshold: float
    breached: bool
    citation: str
    llm_annotation: str | None = None
    human_review: bool = False


def load_financials(path: str | Path) -> list[MonthlyFinancial]:
    with Path(path).open(newline="") as handle:
        rows = csv.DictReader(handle)
        return [
            MonthlyFinancial(
                month=row["month"],
                arr_millions=float(row["arr_millions"]),
                mrr_millions=float(row["mrr_millions"]),
                churn_pct=float(row["churn_pct"]),
                gross_burn_millions=float(row["gross_burn_millions"]),
                cash_balance_millions=float(row["cash_balance_millions"]),
                headcount=int(row["headcount"]),
                nrr_pct=float(row["nrr_pct"]),
                notes=row["notes"],
            )
            for row in rows
        ]


def monitor_covenants(financials: list[MonthlyFinancial]) -> list[CovenantResult]:
    results: list[CovenantResult] = []
    by_month = {item.month: item for item in financials}
    for idx, item in enumerate(financials):
        runway = item.cash_balance_millions / item.gross_burn_millions
        liquidity_breach = item.cash_balance_millions < 8.0 or runway < 4.0
        results.append(CovenantResult(item.month, "minimum_liquidity_cash_runway", runway, 4.0, liquidity_breach, "loan_agreement.md §4.1"))

        prior_year = f"{int(item.month[:4]) - 1}{item.month[4:]}"
        if prior_year in by_month:
            prior_arr = by_month[prior_year].arr_millions
            growth = (item.arr_millions - prior_arr) / prior_arr * 100
            results.append(CovenantResult(item.month, "arr_growth_floor", growth, 20.0, growth < 20.0, "loan_agreement.md §4.2"))

        results.append(CovenantResult(item.month, "nrr_floor", item.nrr_pct, 100.0, item.nrr_pct < 100.0, "loan_agreement.md §4.4"))

        if idx >= 2:
            quarter = financials[idx - 2 : idx + 1]
            quarterly_burn = sum(row.gross_burn_millions for row in quarter)
            net_new_arr = item.arr_millions - quarter[0].arr_millions
            annualized_net_new_arr = net_new_arr * 4
            burn_multiple = float("inf") if annualized_net_new_arr <= 0 else quarterly_burn / annualized_net_new_arr
            restatement_review = any("revenue restatement" in row.notes for row in quarter)
            results.append(CovenantResult(item.month, "net_burn_multiple_cap", burn_multiple, 1.5, (burn_multiple > 1.5) and not restatement_review, "loan_agreement.md §4.3", "Restatement period requires analyst validation before covenant action." if restatement_review else None, restatement_review))

        if "ambiguous" in item.notes:
            results.append(CovenantResult(item.month, "committed_mrr_interpretation", item.mrr_millions, 0.0, False, "loan_agreement.md §4.5", "Verbal approval is not countersigned; require human review before including committed MRR.", True))
    return results


def breached_months(results: list[CovenantResult]) -> set[str]:
    return {result.month for result in results if result.breached}
