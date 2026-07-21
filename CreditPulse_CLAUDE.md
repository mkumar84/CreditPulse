# CLAUDE.md — CreditPulse Build Guide

## Project Summary
CreditPulse is a three-agent diligence-and-monitoring copilot for private credit, built against a fictionalized SaaS borrower ("Meridian SaaS Co."). Portfolio prototype for an AI Product Manager interview at a real private-credit fintech — demonstrates covenant-structure fluency, disciplined agent-vs-pipeline judgment, and an evaluation-first build approach. See CreditPulse_PRD.md for full spec.

## Build Philosophy (apply throughout)
- Test-first: eval harness and ground-truth dataset exist before agent logic is finalized.
- Compliance/policy layer before agents: CEL-style gates are scaffolded before agent chaining is wired up.
- Deterministic before generative: any calculation that CAN be done in code (ratios, growth rates, runway) MUST be done in code, never left to an LLM to compute. LLMs interpret ambiguous text; they don't do arithmetic that code can do exactly.
- Options presented before building: if a design decision has real tradeoffs (e.g., which model per agent, how granular the covenant schema should be), surface the options and reasoning before committing.

## Stack
- Frontend: Lovable
- Backend: Railway
- Agents: Claude API for extraction interpretation + memo drafting (highest-stakes step); consider a lighter/cheaper model for raw field extraction if cost matters — mirror the AML WatchAgent pattern (Groq/Llama for lightweight agents, Claude for higher-stakes drafting).
- Data: synthetic, generated once, version-controlled as static files (JSON/CSV) — NOT regenerated per session. Eval numbers must be reproducible for a live interview demo.

## Build Order
1. **Synthetic dataset generation** — 24 months of Meridian SaaS Co. financials (ARR, MRR, churn, gross burn, cash balance, headcount) + a loan agreement document defining covenants:
   - Minimum liquidity / cash runway covenant
   - ARR growth floor (YoY)
   - Net burn multiple / burn-to-growth ratio cap
   - Net revenue retention floor
   Inject exactly 3 anomalies: a revenue restatement, a genuine covenant breach around month 19, and one ambiguous edge case with no clean answer. Store the ground-truth answer key separately — this is what the evals tab scores against.

2. **Extraction agent** — parses the synthetic documents into a structured schema. Every extracted field must carry a source citation (document name + line/section reference). Output format: structured JSON.

3. **Covenant monitor** — deterministic ratio/threshold calculations in code for every covenant type. Separate LLM-interpretation layer only for ambiguous loan-agreement language (e.g., what counts toward "committed MRR"). The two outputs must be visually distinct in the UI — computed value vs. LLM-interpreted judgment — never merged into one number.

4. **Policy gates (CEL-style)** — implement as explicit rule checks between stages:
   - Memo cannot cite a figure absent from the extraction table.
   - Covenant monitor's LLM layer can annotate but never override a deterministic calculation.
   - Any covenant breach forces a human-review flag before a memo can be marked final.

5. **Memo drafter** — generates a diligence/monitoring memo in prose. Every factual claim must trace to an extraction-table field. Unsupported claims are rendered as `[NEEDS REVIEW]` inline, never asserted as fact. This is a hard constraint, not a style preference — enforce it structurally (e.g., claim-to-source mapping check before render), not just via prompting.

6. **Evals dashboard** — this is the centerpiece screen, build it with real care:
   - Extraction accuracy % vs. ground truth
   - Covenant breach detection precision/recall (did it catch month-19 breach? false positives?)
   - Memo hallucination rate (% of claims failing source-traceability)
   - Regression view across at least 2 prompt/model iterations
   Use clean charts, not tables of raw numbers — this is the screen shown live in an interview.

## Terminology Discipline
This is a venture-debt / growth-stage lending context, NOT traditional leveraged-loan/LBO covenant language. Use MRR/ARR-based covenant terms, not debt-service-coverage-ratio-style corporate covenant terms, unless explicitly relevant. Getting this wrong undermines the entire credibility purpose of the prototype — double-check terminology against real venture debt term sheets before finalizing copy.

## Non-Goals (do not build)
- No real underwriting/prediction engine — do not imply this replicates any real company's proprietary technology.
- No origination workflow — scope is diligence + monitoring only.
- No open-ended agent autonomy — every agent action must be bounded by a policy gate. This constraint is a deliberate product decision to narrate, not a limitation to work around.

## Repo & Naming
- Public repo under mkumar84, fictionalized company name throughout.
- README must state clearly this is a fictionalized learning/portfolio prototype, not built on or claiming access to any real company's data or technology.

## Deployment Target
Live and stable well before the Pinar Ozmen interview round — no last-minute deploys. Reserve 2-3 days of buffer for a dry-run walkthrough of the evals tab.
