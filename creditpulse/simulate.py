"""Forward covenant projection.

This module does not reimplement any covenant math. It only constructs
hypothetical MonthlyFinancial rows consistent with requested scenario
overrides, then hands the combined historical-prefix + projected rows to
creditpulse.covenants.monitor_covenants() — completely unmodified, the exact
same function used for real historical months. monitor_covenants() performs
100% of the actual ratio calculations and threshold comparisons; this module
never calls an LLM and never touches a threshold value.

Note on the projected_financials figures:

ARR compounds smoothly month over month from the real starting month's
actual ARR, at the constant monthly rate implied by arr_growth_pct (so that
after 12 projected months, ARR is exactly arr_growth_pct higher than the
value 12 months earlier). This deliberately does NOT re-anchor each
projected month to that specific calendar month's value from a year ago —
the historical data has real seasonal shape and a deliberate ARR-restatement
anomaly (April 2026), and re-anchoring to it would import that noise into an
otherwise-constant scenario. Smooth compounding keeps ARR monotonic under
constant inputs, as a "hold this growth rate steady" scenario should be.

One consequence: for projected months within the first 12 of the horizon,
the arr_growth_floor covenant's own year-over-year computation (against the
REAL month 12 months back, which monitor_covenants() computes unmodified)
will not exactly equal arr_growth_pct — only once both endpoints of that
comparison are inside the smooth projected series (13+ months out) does it
become exact. This is the mathematically correct behavior, not a rounding
gap: a real deceleration starting today would take a full trailing-12-month
cycle to show up as an unchanged trailing growth-rate reading too.

Gross burn is solved DIRECTLY per month — gross_burn[M] = burn_multiple *
annualized_net_new_arr[M] / 3 — rather than by chaining backward through the
rolling 3-month window (target[M] - gross_burn[M-2] - gross_burn[M-1]). The
chained form was tried first and rejected: monitor_covenants()'s quarterly
window makes "3 consecutive burns sum to a target" a marginally-stable
recurrence with no damping term, so any transient mismatch at the
historical/projected boundary (the real trailing months were never chosen
to fit the new scenario) becomes a permanent, undamped oscillation — it
does not decay no matter how many months are projected. The direct form
has no such feedback path, so it stays stable indefinitely. Its trade-off
is the mirror of the ARR-growth one above: because net_new_arr drifts
slightly month to month under exponential ARR compounding, the burn-multiple
covenant's own computed_value converges very close to, but is not always
bit-exact to, the requested burn_multiple during the transition — verified
in tests to stay within a small, non-oscillating tolerance, converging
tighter as the projection settles into the new trend.
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
    """Build hypothetical rows via smooth month-over-month compounding from
    the real starting month, at the monthly rate implied by arr_growth_pct,
    then reverse-solve burn through the exact same quarterly-window formula
    monitor_covenants() uses so the requested burn_multiple is (barring the
    Infinity edge case below) what that formula reports back. See the module
    docstring for why ARR is NOT re-anchored to specific historical months.

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
    monthly_growth_factor = (1 + arr_growth_pct / 100) ** (1 / 12)
    projected: list[MonthlyFinancial] = []

    for step in range(1, months_forward + 1):
        month = _add_months(start_month, step)

        arr = timeline[-1].arr_millions * monthly_growth_factor
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
            # Direct solve, not chained through the previous two months'
            # already-solved burns — see the module docstring for why the
            # chained form oscillates without bound.
            gross_burn = burn_multiple * annualized_net_new_arr / 3

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


def describe_result_metadata(result: CovenantResult, projected_months: set[str]) -> dict[str, bool | str]:
    """/simulate-only transparency metadata about whether a covenant's own
    window/comparator (per monitor_covenants(), unmodified) has fully
    rotated into projected months yet. Purely descriptive of month
    membership — does not touch computed_value or any threshold.

    net_burn_multiple_cap uses a 3-month rolling window (this month and the
    two before it); arr_growth_floor compares against the month exactly 12
    months back. Both are read directly from monitor_covenants()'s own
    window definitions, not redefined here.

    Caveat (label purity != numeric settling): window_fully_projected only
    means every month *label* in the window is a projected month. A
    projected month's own value can still be elevated by history it
    inherited when IT was generated (e.g. its own net-new-ARR was computed
    against a still-real prior month) and that value keeps contributing to
    the rolling sum for as long as it sits inside the window. So numeric
    convergence lags window-label purity by up to one extra month — see the
    /simulate PRD section and CreditPulse_PRD.md for a worked example.
    """
    if result.covenant == "net_burn_multiple_cap":
        window_months = (_add_months(result.month, -2), _add_months(result.month, -1), result.month)
        return {"window_fully_projected": all(month in projected_months for month in window_months)}
    if result.covenant == "arr_growth_floor":
        comparator_month = _add_months(result.month, -12)
        return {"comparator_month": comparator_month, "comparator_is_projected": comparator_month in projected_months}
    return {}
