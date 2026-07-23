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
