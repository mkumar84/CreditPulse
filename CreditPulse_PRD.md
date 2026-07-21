# CreditPulse PRD

## Scope

CreditPulse is a three-agent diligence-and-monitoring copilot for a fictionalized venture-debt borrower, Meridian SaaS Co. The product demonstrates how bounded agents can support private-credit monitoring without replacing deterministic calculations, policy gates, or human review.

## Agents and deterministic services

| Component | Role | Guardrail |
| --- | --- | --- |
| Extraction agent | Converts static source documents into cited JSON fields. | Every field must include a document and section/line citation. |
| Covenant monitor | Computes liquidity runway, ARR growth, net burn multiple, and NRR compliance. | Ratios are calculated in code; LLM annotations cannot override them. |
| Memo drafter | Produces cited monitoring prose. | Unsupported factual claims render as `[NEEDS REVIEW]`. |

## Venture-debt covenants

The prototype intentionally uses growth-stage lending terminology: ARR growth floor, minimum liquidity / cash runway, burn-to-growth cap, and net revenue retention floor. It avoids leveraged-loan metrics such as DSCR unless explicitly needed for context.

## Evaluation centerpiece

The evals dashboard should emphasize charts for:

- Extraction accuracy against ground truth.
- Covenant breach detection precision and recall.
- Memo hallucination rate from claim-to-source traceability.
- Regression across at least two prompt/model iterations.
