# CreditPulse PRD

## Scope

CreditPulse is a three-agent diligence-and-monitoring copilot for a fictionalized venture-debt borrower, Meridian SaaS Co. The product demonstrates how bounded agents can support private-credit monitoring without replacing deterministic calculations, policy gates, or human review.

## Agents and deterministic services

| Component | Role | Guardrail |
| --- | --- | --- |
| Extraction agent | Converts static source documents into cited JSON fields. | Every field must include a document and section/line citation. |
| Covenant monitor | Computes liquidity runway, ARR growth, net burn multiple, and NRR compliance. | Ratios are calculated in code; LLM annotations cannot override them. |
| Memo drafter | Produces cited monitoring prose. | Unsupported factual claims render as `[NEEDS REVIEW]`. |

`/ask` is **not** a fourth agent. It is a fixed, deterministic lookup index over the same extraction/covenant data the other three services already produce and cite — see §6. It never calls an LLM to determine a value and never guesses; a question outside its fixed lookup set returns an explicit not-available response instead of a generated answer.

`/simulate` is also **not** a new agent, and does not add a second covenant implementation. It constructs hypothetical monthly rows from scenario overrides and hands them to the exact same `covenants.monitor_covenants()` function `/covenants` uses for real history — every threshold, ratio formula, and breach rule comes from that one function. No LLM is involved.

## Venture-debt covenants

The prototype intentionally uses growth-stage lending terminology: ARR growth floor, minimum liquidity / cash runway, burn-to-growth cap, and net revenue retention floor. It avoids leveraged-loan metrics such as DSCR unless explicitly needed for context.

## Evaluation centerpiece

The evals dashboard should emphasize charts for:

- Extraction accuracy against ground truth.
- Covenant breach detection precision and recall.
- Memo hallucination rate from claim-to-source traceability.
- Regression across at least two prompt/model iterations.


## 6. Backend JSON contract

The Lovable frontend consumes backend JSON from Railway. This repo should expose the following backend-only endpoints rather than building a duplicate frontend:

- `GET /extraction` returns the cited extraction table for borrower, covenant thresholds, latest-period fields, and a full `monthly_series` for all 24 months. Every citation object includes `document` provenance plus section/line/row metadata and a `confidence` score.
- `GET /covenants` returns deterministic covenant results, breach months, and human-review months with calculated values (`computed_value`, `threshold`, `breached`) separated from interpreted fields (`llm_annotation`, `human_review`).
- `GET /memo` returns `model_label`, source-gated memo status, four prose `sections` (`Facility Summary`, `Operating Performance`, `Liquidity & Burn`, `Recommendation`), and a claim-to-source list. Unsupported claims include `source_note: No source — flagged as needs review` and `needs_review: true`.
- `GET /evals` returns summary-card metrics, raw `breach_counts`, field-level `field_accuracy`, `missing_ground_truth` as an empty array once requested field-level fixtures are covered, and prompt/model regression rows for the evals tab.
- `GET /contract` returns all of the above in one mock-contract-compatible document for local frontend wiring.
- `GET /ask?q=<question>` answers a natural-language question against a **fixed set of deterministic lookups** run over the same data `/contract` already serves — no value is recomputed and no LLM determines content. Covers: current ARR/MRR/cash balance/NRR, ARR growth/liquidity-runway/burn-multiple/NRR-floor covenant status, the committed-MRR interpretation, breach months, human-review months, and facility size.
  - Response shape: `{question, matched, lookup, answer, text, sources, message}`.
  - When `matched` is `true`: `answer` carries the deterministic value (plus covenant fields like `threshold`/`breached`/`human_review`/`llm_annotation` where applicable), `text` is a template-generated natural-language sentence built only from that value, `sources` is a non-empty array of `{field, citation, ...}` reusing the exact citation already attached to that field elsewhere in the payload, and `message` is `null`.
  - When `matched` is `false` (the question doesn't match any fixed lookup): `lookup`, `answer` are `null`, `sources` is `[]`, and `message` is a fixed explanatory string. This is the required behavior for anything outside the lookup set — CreditPulse never guesses an answer to a question it can't cite.
- `GET /simulate?months_forward=<int>&arr_growth_pct=<float>&burn_multiple=<float>&start_month=<YYYY-MM>&nrr_pct=<float>` projects covenant status forward from a starting point (`start_month`, default the latest actual month, `2026-12`) under a hypothetical scenario. `months_forward`, `arr_growth_pct`, and `burn_multiple` are required; `start_month` and `nrr_pct` are optional (`nrr_pct` defaults to holding the starting month's actual NRR constant). Returns `400 {error, message}` if a required parameter is missing or non-numeric.
  - Response shape: `{is_simulation: true, start_month, months_forward, overrides, projected_months, breach_months, human_review_months, projected_financials, results}`.
  - `results` has the exact same per-row shape as `/covenants`' `results` (`month`, `covenant`, `computed_value`, `threshold`, `breached`, `citation`, `llm_annotation`, `human_review`) — every threshold and formula in it comes from `covenants.monitor_covenants()` unmodified, never redefined for this endpoint.
  - `projected_financials` exposes the hypothetical monthly inputs (`arr_millions`, `mrr_millions`, `gross_burn_millions`, `cash_balance_millions`, `nrr_pct`) the projection is built from, for transparency about the scenario's assumptions — these are constructed, not extracted, and must never be confused with real data downstream. `is_simulation: true` at the top level exists specifically to make that unambiguous.
  - ARR compounds smoothly month over month at the constant rate implied by `arr_growth_pct`, rather than being re-anchored to each specific historical same-month-last-year value — the latter was tried first and rejected because it imported the real dataset's seasonal shape and its deliberate April-2026 ARR-restatement anomaly into an otherwise-constant scenario, producing a discontinuity right at the projection boundary. One consequence: `arr_growth_floor`'s own year-over-year reading (computed by `covenants.py`, unmodified) only exactly equals `arr_growth_pct` once *both* months being compared are inside the projected series (the 12th projected month onward, since its year-ago comparator is the real starting month itself) — before that it's legitimately still dominated by what actually happened historically, the same way a real trailing-twelve-month metric takes a full year to reflect a regime change.
  - `gross_burn_millions` is solved directly from each month's own quarter (`burn_multiple × annualized net-new-ARR ÷ 3`), not chained backward through the previous two months' already-solved burns — the chained form was tried first and rejected because covenants.py's rolling 3-month window makes that recurrence marginally stable with no damping term, so it oscillates without bound once any transient mismatch appears at the historical/projected boundary. The direct form stays smooth and non-oscillating, converging closer to the requested `burn_multiple` as the projection moves away from that boundary.
  - Ratio comparisons in `covenants.py` (`runway`, `arr_growth`, `burn_multiple`) are rounded to 9 decimal places before the breach threshold check, so ordinary floating-point division noise can't push a value sitting exactly at a threshold into a false breach — this applies to `/covenants` too, not just `/simulate`.
