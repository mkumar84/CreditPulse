# AGENTS.md — CreditPulse Build Guide

## Project Summary

CreditPulse is a three-agent diligence-and-monitoring copilot for private credit, built against a fictionalized SaaS borrower ("Meridian SaaS Co."). Portfolio prototype for an AI Product Manager interview at a real private-credit fintech — demonstrates covenant-structure fluency, disciplined agent-vs-pipeline judgment, and an evaluation-first build approach. See `CreditPulse_PRD.md` for full spec.

This file is tool-agnostic — follow it regardless of which coding assistant is being used (Claude Code, Codex, Cursor, etc.).

## Current State — Read This First

Before making any changes, run the existing quickstart and read what's already implemented:

```bash
python -m pytest
python -m creditpulse.run_demo
```

Already built (per repo structure as of last commit):

- `creditpulse/` — deterministic covenant monitoring, policy gates, eval code, and the Sponsor & Founder Diligence module (founder extraction, wealth estimator, network/concentration flag, adverse media classification)
- `data/synthetic/` — Meridian SaaS Co. financials, loan agreement, and sponsor diligence documents (`founder_bios.md`, `cap_table.md`, `investor_network.json`, `adverse_media_records.md`)
- `data/ground_truth/` — answer keys used by the eval harness, including the sponsor module's wealth-estimate and adverse-media answer keys
- `tests/` — regression tests for covenants, policies, evals, and the sponsor module

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
2. **Extraction agent** — ✅ complete (`creditpulse/extraction.py`). Parses synthetic documents into structured JSON with a document + line/section citation on every field.
3. **Covenant monitor** — ✅ complete (`creditpulse/covenants.py`). Ratio/threshold calculations happen in code; LLM-style annotation (e.g. the MAC-clause `committed_mrr_interpretation` branch) stays a visually/structurally distinct field from `computed_value`, never merged into one number.
4. **Policy gates (CEL-style)** — ✅ complete (`creditpulse/policy.py`). All three rules enforced: memo claims are checked against real extraction fields (`render_claim`), the covenant monitor's interpretive fields never override a computed value, and `final_memo_allowed()` blocks finalization on an unresolved breach.
5. **Memo drafter** — ✅ complete (`creditpulse/memo_drafter.py`, live Claude call with a deterministic fallback claim set). Every claim passes through `render_claim()`'s structural claim-to-source check before it can appear un-flagged.
6. **Evals dashboard data layer** — ✅ complete (`creditpulse/evals.py` + `api.py`'s `build_evals_payload`). Extraction accuracy, covenant precision/recall, memo hallucination rate, and field-level accuracy are all computed against ground-truth fixtures, not hardcoded.
7. **API layer for Railway** — ✅ complete (`creditpulse/api.py`). Exposes `/extraction`, `/covenants`, `/memo`, `/evals`, `/contract`, `/ask`, `/simulate`, and the sponsor-diligence endpoints below in the JSON shape PRD §6 documents.
8. **Sponsor & Founder Diligence module** — ✅ complete. Full spec in `CreditPulse_Sponsor_Diligence_PRD.md`; see `CreditPulse_PRD.md`'s "Sponsor & Founder Diligence module" section and §6 for the shipped endpoint shapes. Built in order: (1) founder profile extraction (`founder_extraction.py`, cited), (2) wealth signal estimator (`wealth_estimator.py`, pure deterministic function, no LLM in the number, explicit `insufficient_data` when disclosed figures don't support an estimate), (3) network graph passthrough + concentration-risk flag via graph traversal (`investor_network.py`), (4) adverse media extraction + LLM-assisted classification with a structural safety gate that never lets an ambiguous record auto-classify as clean (`adverse_media.py`), (5) `/sponsor-profile`, `/sponsor-network`, `/adverse-media` endpoints plus a `sponsor` key on `/contract`, (6) eval harness with ground truth authored independently of the module's own code (`data/ground_truth/wealth_estimate_answer_key.json`, `adverse_media_answer_key.json`), wired into `/evals`'s existing `field_accuracy` array.

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

Live on Railway well before the Pinar Ozmen interview round — no last-minute deploys. Reserve 2-3 days of buffer for a dry-run walkthrough of the evals tab.

Once the API layer (step 7) is deployed, the Lovable frontend needs its mock JSON calls swapped for live fetch calls to the Railway endpoints — flag this as a follow-up task, don't do it inside this build pass unless asked.
