"""Deterministic lookup engine for the /ask endpoint.

No new values are computed here — every answer is read directly from an
already-built /contract payload (extraction + covenants), reusing whatever
citation is already attached to that field elsewhere in the API. This module
never calls an LLM and never guesses: if a question doesn't match one of the
fixed lookups below, answer_question() returns an explicit "not available"
response rather than a plausible-sounding fabrication.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

NOT_AVAILABLE_MESSAGE = (
    "Not available in current data. CreditPulse only answers from a fixed set of cited "
    "lookups (ARR, MRR, cash balance, NRR, cash runway, burn multiple, ARR growth, "
    "committed MRR interpretation, covenant breach months, human-review months, and "
    "facility size). It does not generate answers outside that set."
)


def _fmt(value: Any, kind: str) -> str:
    if isinstance(value, str):  # e.g. "Infinity" for an undefined burn multiple
        return value
    if kind == "money":
        return f"${value:g} million"
    if kind == "percent":
        return f"{value:g}%"
    if kind == "multiple":
        return f"{value:g}x"
    if kind == "months":
        return f"{value:g} months"
    return str(value)


def _contains_word(question: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", question) is not None


def _contains_any(question: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in question for phrase in phrases)


def _latest_covenant_result(contract: dict[str, Any], covenant: str) -> dict[str, Any] | None:
    as_of_month = contract["covenants"]["as_of_month"]
    return next(
        (row for row in contract["covenants"]["results"] if row["covenant"] == covenant and row["month"] == as_of_month),
        None,
    )


def _covenant_answer(contract: dict[str, Any], covenant: str, label: str, kind: str) -> dict[str, Any] | None:
    """Generic resolver for threshold-style covenants (computed value vs. a breach threshold)."""
    row = _latest_covenant_result(contract, covenant)
    if row is None:
        return None
    status = "breached" if row["breached"] else "in compliance"
    text = (
        f"As of {row['month']}, {label} was {_fmt(row['computed_value'], kind)} "
        f"against a {_fmt(row['threshold'], kind)} threshold ({status})."
    )
    if row["human_review"] and row["llm_annotation"]:
        text += f" Flagged for human review: {row['llm_annotation']}"
    return {
        "value": row["computed_value"],
        "as_of_month": row["month"],
        "threshold": row["threshold"],
        "breached": row["breached"],
        "human_review": row["human_review"],
        "llm_annotation": row["llm_annotation"],
        "text": text,
        "sources": [{"field": covenant, "citation": row["citation"]}],
    }


def _committed_mrr_answer(contract: dict[str, Any]) -> dict[str, Any] | None:
    """committed_mrr_interpretation isn't a threshold covenant — it's an interpretive
    flag with no breach condition, so it gets its own (still fully deterministic) text."""
    row = _latest_covenant_result(contract, "committed_mrr_interpretation")
    if row is None:
        return None
    text = f"As of {row['month']}, committed MRR of {_fmt(row['computed_value'], 'money')} requires human review before inclusion."
    if row["llm_annotation"]:
        text += f" {row['llm_annotation']}"
    return {
        "value": row["computed_value"],
        "as_of_month": row["month"],
        "human_review": row["human_review"],
        "llm_annotation": row["llm_annotation"],
        "text": text,
        "sources": [{"field": "committed_mrr_interpretation", "citation": row["citation"]}],
    }


def _extraction_field_answer(contract: dict[str, Any], field: str, label: str, kind: str) -> dict[str, Any] | None:
    payload = contract["extraction"]["latest_month"].get(field)
    if payload is None:
        return None
    month = contract["extraction"]["latest_month"]["month"]["value"]
    text = f"As of {month}, {label} was {_fmt(payload['value'], kind)}."
    return {
        "value": payload["value"],
        "as_of_month": month,
        "text": text,
        "sources": [{"field": field, "citation": payload["citation"]}],
    }


def _facility_size_answer(contract: dict[str, Any]) -> dict[str, Any] | None:
    facility = contract["extraction"].get("facility_size_millions")
    if facility is None:
        return None
    text = f"The committed facility size is {_fmt(facility['value'], 'money')}."
    return {
        "value": facility["value"],
        "text": text,
        "sources": [{"field": "facility_size_millions", "citation": facility["citation"]}],
    }


def _breach_months_answer(contract: dict[str, Any]) -> dict[str, Any]:
    months = contract["covenants"]["breach_months"]
    breached_rows = [row for row in contract["covenants"]["results"] if row["breached"]]
    text = f"A covenant breach occurred in {', '.join(months)}." if months else "No covenant breach has occurred in the monitored period."
    return {
        "value": months,
        "text": text,
        "sources": [{"field": row["covenant"], "month": row["month"], "citation": row["citation"]} for row in breached_rows],
    }


def _human_review_months_answer(contract: dict[str, Any]) -> dict[str, Any]:
    months = contract["covenants"]["human_review_months"]
    flagged_rows = [row for row in contract["covenants"]["results"] if row["human_review"]]
    text = f"Human review is required for {', '.join(months)}." if months else "No months are currently flagged for human review."
    return {
        "value": months,
        "text": text,
        "sources": [
            {"field": row["covenant"], "month": row["month"], "citation": row["citation"], "llm_annotation": row["llm_annotation"]}
            for row in flagged_rows
        ],
    }


Resolver = Callable[[dict[str, Any]], dict[str, Any] | None]


@dataclass(frozen=True)
class Lookup:
    key: str
    matches: Callable[[str], bool]
    resolve: Resolver


# Order matters: more specific multi-word phrases are checked before the bare
# acronyms they contain (e.g. "arr growth" before bare "arr", "committed mrr"
# before bare "mrr") so the more precise lookup wins on an ambiguous question.
LOOKUPS: tuple[Lookup, ...] = (
    Lookup(
        "committed_mrr_interpretation_status",
        lambda q: _contains_any(q, ("committed mrr", "mac-style", "mac style", "pilot expansion")),
        _committed_mrr_answer,
    ),
    Lookup(
        "arr_growth_floor_status",
        lambda q: _contains_any(q, ("arr growth", "growth floor")),
        lambda c: _covenant_answer(c, "arr_growth_floor", "ARR growth", "percent"),
    ),
    Lookup(
        "nrr_floor_status",
        lambda q: _contains_any(q, ("nrr floor", "nrr covenant", "revenue retention floor", "revenue retention covenant")),
        lambda c: _covenant_answer(c, "nrr_floor", "net revenue retention", "percent"),
    ),
    Lookup(
        "liquidity_runway_status",
        lambda q: _contains_any(q, ("runway", "liquidity covenant", "minimum liquidity")),
        lambda c: _covenant_answer(c, "minimum_liquidity_cash_runway", "cash runway", "months"),
    ),
    Lookup(
        "burn_multiple_status",
        lambda q: _contains_any(q, ("burn multiple", "burn rate multiple")),
        lambda c: _covenant_answer(c, "net_burn_multiple_cap", "the net burn multiple", "multiple"),
    ),
    Lookup(
        "breach_months",
        lambda q: "breach" in q,
        _breach_months_answer,
    ),
    Lookup(
        "human_review_months",
        lambda q: _contains_any(q, ("human review", "needs review", "flagged for review", "review required")),
        _human_review_months_answer,
    ),
    Lookup(
        "facility_size",
        lambda q: _contains_any(q, ("facility size", "facility amount", "loan amount", "size of the facility", "facility principal")),
        _facility_size_answer,
    ),
    Lookup(
        "current_cash_balance",
        lambda q: _contains_any(q, ("cash balance", "cash on hand")),
        lambda c: _extraction_field_answer(c, "cash_balance_millions", "the cash balance", "money"),
    ),
    Lookup(
        "current_nrr",
        lambda q: _contains_word(q, "nrr") or "net revenue retention" in q,
        lambda c: _extraction_field_answer(c, "nrr_pct", "net revenue retention", "percent"),
    ),
    Lookup(
        "current_arr",
        lambda q: _contains_word(q, "arr"),
        lambda c: _extraction_field_answer(c, "arr_millions", "ARR", "money"),
    ),
    Lookup(
        "current_mrr",
        lambda q: _contains_word(q, "mrr"),
        lambda c: _extraction_field_answer(c, "mrr_millions", "MRR", "money"),
    ),
)


def answer_question(question: str, contract: dict[str, Any]) -> dict[str, Any]:
    """Answer a question using only the fixed, deterministic lookups in LOOKUPS,
    reading exclusively from an already-built /contract payload. Returns the
    NOT_AVAILABLE_MESSAGE response for anything outside that fixed set — never
    a guessed or generated answer.
    """
    normalized = question.strip().lower()
    if normalized:
        for lookup in LOOKUPS:
            if not lookup.matches(normalized):
                continue
            resolved = lookup.resolve(contract)
            if resolved is None:
                continue
            answer = {k: v for k, v in resolved.items() if k not in ("sources", "text")}
            return {
                "question": question,
                "matched": True,
                "lookup": lookup.key,
                "answer": answer,
                "text": resolved["text"],
                "sources": resolved["sources"],
                "message": None,
            }
    return {
        "question": question,
        "matched": False,
        "lookup": None,
        "answer": None,
        "text": None,
        "sources": [],
        "message": NOT_AVAILABLE_MESSAGE,
    }
