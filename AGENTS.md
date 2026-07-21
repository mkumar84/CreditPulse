# AGENTS.md — CreditPulse Build Guide

## Project Summary
CreditPulse is a three-agent diligence-and-monitoring copilot for private credit, built against a fictionalized SaaS borrower ("Meridian SaaS Co."). Portfolio prototype for an AI Product Manager interview at a real private-credit fintech — demonstrates covenant-structure fluency, disciplined agent-vs-pipeline judgment, and an evaluation-first build approach. See `CreditPulse_PRD.md` for full spec.

This file is tool-agnostic — follow it regardless of which coding assistant is being used (Claude Code, Codex, Cursor, etc.).

## Current State — Read This First
Before making any changes, run the existing quickstart and read what's already implemented:
```
python -m pytest
python -m creditpulse.run_demo
```
Already built (per repo structure as of last commit):
- `creditpulse/` — deterministic covenant monitoring, policy gates, eval code
- `data/synthetic/` — Meridian SaaS Co. financials and loan agreement documents
- `data/ground_truth/` — answer keys used by the eval harness
- `tests/` — regression tests for covenants, policies, and evals

**Do not regenerate the synthetic dataset or restructure existing modules unless something is broken.** Extend what exists — confirm what's implemented vs. still missing from the Build Order below, then continue from the first incomplete step.

## Build Philosophy (apply throughout)
- Test-first: eval harness and ground-truth dataset exist before agent logic is finalized. (Already true here — don't undo it.)
- Compliance/policy layer before agents: CEL-style gates are scaffolded before agent chaining is wired up.
- Deterministic before generative: any calculation that CAN be done in code (ratios, growth rates, runway) MUST be done in code, never left to an LLM to compute. LLMs interpret ambiguous text; they don't do arithmetic that code can do exactly. This is the single most important constraint in this project — verify it explicitly on any new code touching covenant math.
- Options presented before building: if a design decision has real tradeoffs (e.g., which model per agent, how granular the covenant schema should be), surface the options and reasoning before committing.

## Stack
- Frontend: Lovable (already built, currently wired to mocked JSON — do not touch unless asked)
- Backend: Railway (deployment target once agents are complete)
- Agents: Claude API for extraction interpretation + memo drafting (highest-stakes step); consider a lighter/cheaper model for raw field extraction if cost matters — mirror the AML WatchAgent pattern (Groq/Llama for lightweight agents, Claude for higher-stakes drafting).
- Data: synthetic, generated once, version-controlled as static files (JSON/CSV) — NOT regenerated per session. Eval numbers must be reproducible for a live interview demo.

## Build Order — Confirm Status of Each Before Proceeding

1. **Synthetic dataset generation** — ✅ likely complete (`data/synthetic/`, `data/ground_truth/`). Verify it includes: 24 months of Meridian SaaS Co. financials (ARR, MRR, churn, gross burn, cash balance, headcount), a loan agreement defining covenants (minimum liquidity/runway, ARR growth floor, net burn multiple cap, net revenue retention floor), and 3 injected anomalies (a revenue restatement, a genuine covenant breach around month 19, one ambiguous edge case). If any of these are missing, add them — do not regenerate the rest.

2. **Extraction agent** — confirm whether this exists yet. Should parse synthetic documents into a structured schema, with every field carrying a source citation (document name + line/section reference). Output format: structured JSON.

3. **Covenant monitor** — ✅ likely complete given "deterministic covenant monitoring" in repo description. Verify: ratio/threshold calculations happen in code, with a separate LLM-interpretation layer only for ambiguous loan-agreement language. The two outputs must remain visually/structurally distinct — computed value vs. LLM-interpreted judgment — never merged into one number.

4. **Policy gates (CEL-style)** — ✅ likely complete ("policy gates" in repo description). Verify these three rules are enforced:
   - Memo cannot cite a figure absent from the extraction table.
   - Covenant monitor's LLM layer can annotate but never override a deterministic calculation.
   - Any covenant breach forces a human-review flag before a memo can be marked final.

5. **Memo drafter** — confirm whether this exists yet. Should generate a diligence/monitoring memo in prose; every factual claim must trace to an extraction-table field. Unsupported claims render as `[NEEDS REVIEW]` inline, never asserted as fact. Enforce this structurally (claim-to-source mapping check before render), not just via prompting.

6. **Evals dashboard data layer** — ✅ likely complete given `run_demo` already prints extraction accuracy, covenant precision/recall, memo hallucination rate, and prompt/model iteration metrics. Confirm these numbers are wired to real computation against ground truth, not hardcoded placeholders.

7. **API layer for Railway** — likely still missing. Needs endpoints exposing extraction table, covenant status, memo output, and eval metrics in the JSON shape Lovable's frontend expects (see PRD §6 for the mocked JSON contract Lovable was built against). This is probably the next real gap to close.

## Terminology Discipline
This is a venture-debt / growth-stage lending context, NOT traditional leveraged-loan/LBO covenant language. Use MRR/ARR-based covenant terms, not debt-service-coverage-ratio-style corporate covenant terms, unless explicitly relevant. Getting this wrong undermines the entire credibility purpose of the prototype — double-check terminology against real venture debt term sheets before finalizing copy or code comments.

## Non-Goals (do not build)
- No real underwriting/prediction engine — do not imply this replicates any real company's proprietary technology.
- No origination workflow — scope is diligence + monitoring only.
- No open-ended agent autonomy — every agent action must be bounded by a policy gate. This constraint is a deliberate product decision to narrate, not a limitation to work around.

## Repo & Naming
- Public repo under mkumar84, fictionalized company name throughout (already correctly set up).
- README must continue to state clearly this is a fictionalized learning/portfolio prototype, not built on or claiming access to any real company's data or technology (already correctly stated — preserve this).

## Deployment Target
Live on Railway well before the Pinar Ozmen interview round — no last-minute deploys. Reserve 2-3 days of buffer for a dry-run walkthrough of the evals tab. Once the API layer (step 7) is deployed, the Lovable frontend needs its mock JSON calls swapped for live fetch calls to the Railway endpoints — flag this as a follow-up task, don't do it inside this build pass unless asked.
