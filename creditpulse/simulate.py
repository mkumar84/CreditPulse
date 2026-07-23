"""Forward covenant projection.

This module does not reimplement any covenant math. It only constructs
hypothetical MonthlyFinancial rows consistent with requested scenario
overrides, then hands the combined historical-prefix + projected rows to
creditpulse.covenants.monitor_covenants() — completely unmodified, the exact
same function used for real historical months. monitor_covenants() performs
100% of the actual ratio calculations and threshold comparisons; this module
never calls an LLM and never touches a threshold value.

Note on the projected_financials figures: ARR is anchored to the real,
same-calendar-month value from a year earlier (so a covenant check comparing
year-over-year growth sees exactly the requested arr_growth_pct). That
anchor inherits whatever seasonal unevenness is already in the historical
data, which the burn-multiple covenant's quarterly window is sensitive to —
so the *implied* gross_burn solved to hit a requested burn_multiple can look
large or even negative in a volatile scenario. That is a real mathematical
consequence of forcing a constant ratio against a jagged ARR delta, not an
estimation error; the covenant verdicts it produces are still exactly
correct (verified in tests), including reproducing monitor_covenants()'s own
"Infinity" rule when quarterly net-new-ARR is zero or negative.
"""

from __future__ import annotations

from dataclasses import dataclass

from creditpulse.covenants import CovenantResult, MonthlyFinancial, monitor_covenants


@dataclass(frozen=True)
class SimulationResult:
    results: list[CovenantResult]
    projected_rows: list[MonthlyFinancial]


def _add_months(month: str, delta: int) -> str:
    year, mon = (int(part) for part in month.split("-"))
    total = year * 12 + (mon - 1) + delta
    new_year, new_month = divmod(total, 12)
    return f"{new_year:04d}-{new_month + 1:02d}"


def _generate_projected_rows(
    historical: list[MonthlyFinancial],
    start_month: str,
    months_forward: int,
    arr_growth_pct: float,
    burn_multiple: float,
    nrr_pct: float | None,
) -> list[MonthlyFinancial]:
    """Build hypothetical rows so that, once run through monitor_covenants()
    unmodified, its arr_growth_floor/net_burn_multiple_cap computed_values
    come out equal to the requested overrides — by construction, using the
    exact inverse of the same formulas monitor_covenants() applies forward
    (YoY ARR growth against the same calendar month prior year; quarterly
    gross burn / annualized quarterly net-new-ARR for burn multiple).

    Cash balance has no override: it rolls forward as
    cash[month] = cash[prior month] - gross_burn[month], the simplest
    assumption consistent with the runway formula (cash depletes by burn) —
    there is no way to "reuse" a historical cash trajectory for months that,
    by definition, never actually happened.
    """
    by_month = {row.month: row for row in historical}
    if start_month not in by_month:
        raise ValueError(f"Unknown start_month: {start_month!r}")
    start_index = next(i for i, row in enumerate(historical) if row.month == start_month)
    timeline = list(historical[: start_index + 1])

    starting_row = by_month[start_month]
    effective_nrr = starting_row.nrr_pct if nrr_pct is None else nrr_pct
    cash_balance = starting_row.cash_balance_millions
    projected: list[MonthlyFinancial] = []

    for step in range(1, months_forward + 1):
        month = _add_months(start_month, step)
        prior_year_month = _add_months(month, -12)
        prior_year_row = by_month.get(prior_year_month) or next((row for row in timeline if row.month == prior_year_month), None)
        if prior_year_row is None:
            raise ValueError(f"Cannot project {month}: no prior-year data available for {prior_year_month}.")

        arr = prior_year_row.arr_millions * (1 + arr_growth_pct / 100)
        mrr = arr / 12

        quarter_prior = timeline[-2:]
        net_new_arr = arr - quarter_prior[0].arr_millions
        annualized_net_new_arr = net_new_arr * 4
        if annualized_net_new_arr <= 0:
            # monitor_covenants() itself reports burn multiple as Infinity
            # whenever quarterly net-new-ARR is zero or negative (see
            # covenants.py), regardless of the burn value — so there is no
            # finite gross_burn that makes "hit the target ratio" meaningful
            # here. Hold burn flat at the prior month's rate instead of
            # solving a division that covenants.py would never perform.
            gross_burn = quarter_prior[-1].gross_burn_millions
        else:
            target_quarterly_burn = burn_multiple * annualized_net_new_arr
            prior_burn_sum = sum(row.gross_burn_millions for row in quarter_prior)
            gross_burn = target_quarterly_burn - prior_burn_sum

        cash_balance = cash_balance - gross_burn

        row = MonthlyFinancial(
            month=month,
            arr_millions=round(arr, 6),
            mrr_millions=round(mrr, 6),
            churn_pct=starting_row.churn_pct,
            gross_burn_millions=round(gross_burn, 6),
            cash_balance_millions=round(cash_balance, 6),
            headcount=starting_row.headcount,
            nrr_pct=effective_nrr,
            notes="simulated projection",
        )
        timeline.append(row)
        projected.append(row)

    return projected


def simulate_covenants(
    historical: list[MonthlyFinancial],
    start_month: str,
    months_forward: int,
    arr_growth_pct: float,
    burn_multiple: float,
    nrr_pct: float | None = None,
) -> SimulationResult:
    """Project covenant status forward from start_month under a hypothetical
    scenario. The only covenant math performed is inside monitor_covenants();
    this function's job is entirely input construction and result filtering.
    """
    projected_rows = _generate_projected_rows(historical, start_month, months_forward, arr_growth_pct, burn_multiple, nrr_pct)
    start_index = next(i for i, row in enumerate(historical) if row.month == start_month)
    combined = historical[: start_index + 1] + projected_rows
    all_results = monitor_covenants(combined)
    projected_months = {row.month for row in projected_rows}
    results = [result for result in all_results if result.month in projected_months]
    return SimulationResult(results=results, projected_rows=projected_rows)
