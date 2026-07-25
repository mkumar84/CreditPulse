# CreditPulse — Sponsor & Founder Diligence Module (PRD + Build Guide)

## Purpose

Add a fourth pillar to CreditPulse: diligence on *who* is being lent to, 
not just the financials. Real underwriting always includes sponsor/founder 
assessment — this closes a real gap in the existing build and demonstrates 
judgment on a genuinely sensitive data domain (personal/financial 
background information), not just technical execution.

## Explicit Framing — Read Before Building Anything

This module deals with information categories that are legitimately 
sensitive in real underwriting (personal wealth, litigation history, 
professional network). The whole module must be built on three rules:

1. **Everything is synthetic and fictional**, same as the rest of 
   CreditPulse (Meridian SaaS Co.'s founders are invented people, not 
   real individuals — never use a real person's name, bio, or history).
2. **No field claims certainty it doesn't have.** Wealth is never shown 
   as a bare number — always a range with a confidence level and a 
   "how this was estimated" note. Legal/adverse-media items are never 
   auto-scored good/bad — ambiguous items route to human review, exactly 
   like the MAC clause pattern already established.
3. **Ground truth for this module's evals must be sourced independently 
   from the extraction logic**, from day one — do not repeat the 
   MAC-style tautology mistake from earlier in the build. Build the 
   answer key from the synthetic source documents directly, never from 
   what the extraction agent outputs.

## New Synthetic Data Needed

Create these under `data/synthetic/`, following the existing pattern 
(fictionalized, consistent with Meridian SaaS Co.):

1. **`founder_bios.md`** — 2-3 fictional founders/executives for Meridian 
   SaaS Co. Each with: name, role, one-paragraph bio, education, 2-3 
   prior ventures with disclosed outcomes (e.g., "co-founded X, acquired 
   by Y in 2021 for an undisclosed amount" or "founded Z, shut down 
   2019"). Include enough variety that at least one founder has a clean 
   record and one has something a diligence process should flag (e.g., 
   a prior company that had a regulatory inquiry, disclosed and 
   resolved).

2. **`cap_table.md`** — Equity ownership: founders' stakes, investor 
   stakes by round (seed, Series A, Series B), board composition.

3. **`investor_network.json`** — Structured data for the network graph: 
   nodes (founders, Meridian SaaS Co., each investor, each board member, 
   each founder's prior companies) and edges (invested_in, board_seat, 
   co_founded, previously_worked_at). Keep it realistically 
   interconnected — e.g., one investor also backs two of the same 
   portfolio companies as another investor, creating a real concentration 
   pattern worth surfacing.

4. **`adverse_media_records.md`** — 2-3 synthetic litigation/regulatory 
   items across the founders and their prior companies. Make at least 
   one clearly immaterial (a resolved, minor contract dispute) and at 
   least one genuinely ambiguous (an ongoing, unresolved regulatory 
   inquiry with no clear outcome yet) — the ambiguous one is what the 
   human-review routing is for.

## Build Order

### 1. Founder Profile Extraction
New extraction sub-agent (or extend the existing one) pulling founder 
bios into structured cards: name, role, education, prior ventures with 
outcomes — every field cited to `founder_bios.md`, same citation pattern 
as existing extraction fields.

### 2. Wealth Signal Estimator (deterministic + labeled estimate)
- Compute an **estimated range**, not a point figure, derived from: 
  disclosed prior exit values (if any) × estimated founder equity % at 
  exit + current cap table stake in Meridian SaaS Co. × latest 
  implied valuation (if disclosed).
- This calculation is deterministic (pure arithmetic on disclosed 
  figures) — no LLM involved in producing the number itself.
- Output must include: the range, a confidence label (e.g., "low / 
  medium confidence" based on how much disclosed data exists), and a 
  plain-language methodology note ("estimated from disclosed prior exit 
  and current cap table stake — not a verified net worth figure").
- If a founder has no disclosed prior exits and no way to estimate 
  reasonably, the field must say so explicitly rather than guessing — 
  same "honest gap" pattern as `missing_ground_truth`.

### 3. Network Graph Data
Serve `investor_network.json` as-is via a new endpoint (e.g., 
`/sponsor-network`) — nodes and edges, no LLM processing needed, this is 
structured data passthrough. Include a simple concentration-risk flag: 
e.g., "2 investors share board seats across 2+ shared portfolio 
companies" if the synthetic data supports detecting this deterministically 
(a graph algorithm, not an LLM judgment).

### 4. Adverse Media / Legal Flag Agent
- Extraction of litigation/regulatory items from 
  `adverse_media_records.md`, each cited.
- Classification into: **Resolved/Immaterial**, **Ongoing/Ambiguous — 
  Human Review Required**, using the same LLM-interpretation-with-
  human-review-flag pattern as the MAC clause. Never auto-classify an 
  ambiguous item as "clean."

### 5. Eval Harness for This Module (build ground truth independently, day one)
- For the wealth signal: ground truth is the actual disclosed figures 
  in the synthetic source docs (not the extraction agent's output) — 
  verify the estimator's arithmetic against a manually-computed expected 
  range.
- For adverse media classification: ground truth is your own independent 
  read of each synthetic record (which one is genuinely ambiguous, which 
  is genuinely resolved) — written before or independently of running the 
  classification agent, not copied from its output.
- Add this to the existing `field_accuracy` / `missing_ground_truth` 
  pattern so it shows up in the same Evals dashboard, not a separate 
  disconnected page.

## API Additions
- `/sponsor-profile` — founder cards + wealth signal
- `/sponsor-network` — graph nodes/edges + concentration flag
- `/adverse-media` — litigation/regulatory items + classification
- Extend `/contract` to include all three under a new `sponsor` key
- Extend `/evals` to include this module's field_accuracy entries

## Non-Goals (explicit)
- No real data scraping of any kind, ever — everything is synthetic, 
  same as the rest of the app.
- No actual net worth claims — estimated ranges with methodology and 
  confidence only.
- No automated "risk score" that collapses legal/adverse-media findings 
  into a single pass/fail number — ambiguous items always route to 
  human review, never auto-resolved.
