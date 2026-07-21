# CreditPulse

CreditPulse is a fictionalized learning and portfolio prototype for private-credit diligence and monitoring workflows. It uses a synthetic venture-debt borrower, **Meridian SaaS Co.**, and does **not** use, claim access to, or replicate any real company's private data, proprietary workflows, underwriting models, or technology.

The prototype is designed around an evaluation-first, policy-gated agent architecture:

1. Version-controlled synthetic data and ground truth.
2. Structured extraction with source citations.
3. Deterministic covenant monitoring for all computable ratios.
4. CEL-style policy gates between stages.
5. Source-traceable memo drafting.
6. An evals dashboard dataset for interview walkthroughs.

## Quickstart

```bash
python -m pytest
python -m creditpulse.run_demo
```

The demo prints extraction accuracy, covenant precision/recall, memo hallucination rate, and prompt/model iteration metrics derived from static, cited fixtures. The extraction table is stored as JSON so every demo metric is reproducible and traceable to a source document or CSV row.

## Project structure

```text
creditpulse/                  Core deterministic monitoring, policy, and eval code
data/synthetic/               Static Meridian SaaS Co. documents and monthly metrics
data/ground_truth/            Answer keys used by the eval harness
tests/                        Regression tests for covenants, policies, and evals
CreditPulse_PRD.md            Product requirements and build plan
```
