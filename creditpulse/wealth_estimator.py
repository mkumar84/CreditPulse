"""Deterministic founder wealth signal estimator.

Pure arithmetic on disclosed source figures only — no LLM is involved in
producing the number. Per CreditPulse_Sponsor_Diligence_PRD.md: wealth is
never shown as a bare point figure, and a founder with no usable disclosed
data gets an explicit "insufficient data" result rather than a guess.

Two components, each counted only when genuinely disclosed:
  1. Prior-exit proceeds: disclosed exit value x disclosed founder equity %
     at that exit, per prior venture. A venture that shut down with no
     proceeds contributes exactly $0 (a fact stated in the source, not a
     guess) but does NOT count as "disclosed data" toward confidence,
     since no wealth-generating event occurred. A venture disclosed only
     as "acquired for an undisclosed amount" (no exit value, or no
     founder equity % at exit) contributes nothing and is not guessed at.
  2. Current stake: founder's fully-diluted % in the cap table (only if
     finalized, not "pending ratification") x the latest disclosed
     implied valuation.

Confidence is a direct count of how many of those two components have
real disclosed data behind them — never a judgment call:
  - both disclosed  -> "medium confidence"
  - exactly one      -> "low confidence"
  - neither           -> insufficient data, no range returned at all

The uncertainty band around the point estimate is tied to that same count,
not an independent flat number: it scales as BASE_RANGE_BAND_PCT x
(TOTAL_WEALTH_COMPONENTS / disclosed_component_count). At full disclosure
(2/2) that's the base 25%; at partial disclosure (1/2) it doubles to 50%.
This intentionally does NOT try to price in "wealth we don't know about at
all" (undisclosed assets, other ventures) — that's genuinely unknowable and
guessing a number for it would fabricate a precision this module doesn't
have. What it DOES do is keep the displayed range and the confidence label
consistent with each other: a "low confidence" estimate is backed by half
as much disclosed input as a "medium confidence" one, so its band is
proportionally wider, not the same width dressed up with a lower-confidence
sticker next to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from creditpulse.founder_extraction import CapTable, FounderProfile

# Base uncertainty band, applied when both possible components are
# disclosed (full information). Not tuned per founder — a single
# documented modeling assumption, since disclosed equity percentages and
# implied valuations are themselves approximations, not verified/audited
# figures. The actual band used narrows/widens from here based on how many
# of TOTAL_WEALTH_COMPONENTS are actually disclosed — see module docstring.
BASE_RANGE_BAND_PCT = 0.25

# Prior-exit proceeds and current cap table stake — the only two inputs
# this estimator ever considers. Used to scale the band by how much of
# that total is actually backed by disclosed data.
TOTAL_WEALTH_COMPONENTS = 2

NOT_AVAILABLE_METHODOLOGY = (
    "No disclosed prior-exit proceeds and no finalized cap table stake exist "
    "for this individual — insufficient disclosed data to estimate a wealth "
    "signal. This is not a zero estimate; it is an explicit absence of "
    "estimable data."
)


@dataclass(frozen=True)
class WealthEstimate:
    founder_name: str
    insufficient_data: bool
    range_low_millions: float | None
    range_high_millions: float | None
    point_estimate_millions: float | None
    confidence: str | None  # "medium" | "low" | None (when insufficient_data)
    range_band_pct: float | None  # the actual +/- band applied; None when insufficient_data
    methodology_note: str
    prior_exit_component_millions: float
    current_stake_component_millions: float
    disclosed_component_count: int
    sources: tuple[dict[str, Any], ...]


def estimate_wealth(profile: FounderProfile, cap_table: CapTable) -> WealthEstimate:
    """Compute a founder's wealth signal range from disclosed figures only."""
    prior_exit_component = 0.0
    prior_exit_disclosed = False
    sources: list[dict[str, Any]] = []

    for venture in profile.prior_ventures:
        if venture.shut_down_no_proceeds:
            continue  # contributes $0; not counted as disclosed wealth data
        if venture.exit_value_millions is not None and venture.founder_equity_pct_at_exit is not None:
            prior_exit_component += venture.exit_value_millions * (venture.founder_equity_pct_at_exit / 100)
            prior_exit_disclosed = True
            sources.append({"field": f"prior_venture:{venture.company}", "citation": venture.citation})

    current_stake_component = 0.0
    current_stake_disclosed = False
    cap_entry = cap_table.entry_for(profile.name)
    if cap_entry is not None and cap_entry.fully_diluted_pct is not None:
        current_stake_component = cap_table.latest_implied_valuation_millions * (cap_entry.fully_diluted_pct / 100)
        current_stake_disclosed = True
        sources.append({"field": "cap_table_stake", "citation": cap_entry.citation})
        sources.append({"field": "latest_implied_valuation", "citation": cap_table.valuation_citation})

    disclosed_component_count = int(prior_exit_disclosed) + int(current_stake_disclosed)

    if disclosed_component_count == 0:
        return WealthEstimate(
            founder_name=profile.name,
            insufficient_data=True,
            range_low_millions=None,
            range_high_millions=None,
            point_estimate_millions=None,
            confidence=None,
            range_band_pct=None,
            methodology_note=NOT_AVAILABLE_METHODOLOGY,
            prior_exit_component_millions=0.0,
            current_stake_component_millions=0.0,
            disclosed_component_count=0,
            sources=(),
        )

    point_estimate = prior_exit_component + current_stake_component
    range_band_pct = BASE_RANGE_BAND_PCT * (TOTAL_WEALTH_COMPONENTS / disclosed_component_count)
    range_low = round(point_estimate * (1 - range_band_pct), 1)
    range_high = round(point_estimate * (1 + range_band_pct), 1)
    confidence = "medium" if disclosed_component_count == 2 else "low"

    included_parts = []
    if prior_exit_disclosed:
        included_parts.append(f"disclosed prior-exit proceeds (${prior_exit_component:.1f}M, from disclosed exit value x disclosed founder equity % at exit)")
    if current_stake_disclosed:
        included_parts.append(f"current Meridian cap table stake at the latest disclosed implied valuation (${current_stake_component:.1f}M)")
    band_note = (
        f"a +/-{int(BASE_RANGE_BAND_PCT * 100)}% band"
        if disclosed_component_count == TOTAL_WEALTH_COMPONENTS
        else f"a +/-{int(round(range_band_pct * 100))}% band (widened from the {int(BASE_RANGE_BAND_PCT * 100)}% base band since only {disclosed_component_count} of {TOTAL_WEALTH_COMPONENTS} possible components are disclosed — {confidence} confidence)"
    )
    methodology_note = (
        f"Estimated from {' and '.join(included_parts)}. "
        f"Range reflects {band_note} around the ${point_estimate:.1f}M point estimate, "
        "to account for disclosed figures being approximations, not verified or audited net worth. "
        "This is not a verified net worth figure."
    )

    return WealthEstimate(
        founder_name=profile.name,
        insufficient_data=False,
        range_low_millions=range_low,
        range_high_millions=range_high,
        point_estimate_millions=round(point_estimate, 1),
        confidence=confidence,
        range_band_pct=range_band_pct,
        methodology_note=methodology_note,
        prior_exit_component_millions=round(prior_exit_component, 1),
        current_stake_component_millions=round(current_stake_component, 1),
        disclosed_component_count=disclosed_component_count,
        sources=tuple(sources),
    )
