"""Live memo drafting via the Claude API.

This module only proposes claims. It never bypasses the deterministic policy
gate in creditpulse.policy — every claim it returns still has its
field_names checked against real, cited extraction fields by render_claim()
before it can appear in a finalized memo.
"""

from __future__ import annotations

import json
import os
from typing import Any

from creditpulse.policy import ExtractedField, MemoClaim

MEMO_MODEL = "claude-sonnet-5"

MEMO_SECTIONS = ("Facility Summary", "Operating Performance", "Liquidity & Burn", "Recommendation")

CLAIM_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "One factual sentence for the memo."},
                    "section": {"type": "string", "enum": list(MEMO_SECTIONS)},
                    "field_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Extraction/covenant field names that support this claim.",
                    },
                },
                "required": ["text", "section", "field_names"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["claims"],
    "additionalProperties": False,
}


def draft_memo_claims(
    fields: dict[str, ExtractedField], covenant_payload: dict[str, Any]
) -> tuple[list[MemoClaim], list[str]] | None:
    """Draft memo claims with the Claude API, or return None if unavailable.

    Returns (claims, section_per_claim), or None when there is no API key or
    the call/parse fails — callers are expected to fall back to a
    deterministic claim set in that case.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    import anthropic  # deferred: only required when a live call is possible

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=MEMO_MODEL,
            max_tokens=2000,
            output_config={
                "format": {"type": "json_schema", "schema": CLAIM_SCHEMA},
                "effort": "medium",
            },
            messages=[{"role": "user", "content": _build_prompt(fields, covenant_payload)}],
        )
    except Exception:
        return None

    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        return None

    try:
        raw_claims = json.loads(text)["claims"]
        claims = [MemoClaim(claim["text"], tuple(claim["field_names"])) for claim in raw_claims]
        sections = [claim["section"] for claim in raw_claims]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

    if not claims:
        return None
    return claims, sections


def _build_prompt(fields: dict[str, ExtractedField], covenant_payload: dict[str, Any]) -> str:
    field_lines = "\n".join(f"- {name}: {field.value} (source: {field.citation})" for name, field in fields.items())
    breach_months = ", ".join(covenant_payload["breach_months"]) or "none"
    return (
        "You are drafting a private-credit monitoring memo for a venture-debt lender. "
        f"Write concise factual claims covering these sections, in order: {', '.join(MEMO_SECTIONS)}.\n\n"
        "Every claim must be supported ONLY by the cited fields listed below — do not "
        "introduce any fact, number, or field name that is not listed. For each claim, "
        "list the exact field name(s) it relies on in field_names.\n\n"
        f"Cited fields:\n{field_lines}\n\n"
        f"Covenant breach months: {breach_months}\n"
        "If there is a breach, the Recommendation section must state that human review "
        "is required before finalizing the memo."
    )
