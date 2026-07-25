"""Adverse media / legal record extraction and classification.

Extraction is deterministic (regex parsing, cited), matching the rest of
this repo's extraction pattern.

Classification into Resolved/Immaterial vs Ongoing/Ambiguous is
LLM-assisted — a live Claude call when ANTHROPIC_API_KEY is set, otherwise
a deterministic keyword fallback — mirroring creditpulse.memo_drafter's
live/fallback pattern. But classification never trusts the LLM (or
fallback) alone: a structural keyword safety gate runs on every proposed
classification afterward and forces "ongoing_ambiguous" whenever a
record's OWN text contains clear unresolved language, regardless of what
was proposed. This mirrors creditpulse.policy.render_claim's structural
gate (code-enforced, not just prompted) — an ambiguous item is never
auto-classified as clean, even if the LLM or fallback gets it wrong.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RESOLVED_IMMATERIAL = "resolved_immaterial"
ONGOING_AMBIGUOUS = "ongoing_ambiguous"

CLASSIFICATION_MODEL = "claude-sonnet-5"

# Any of these phrases appearing in a record's own status/summary text means
# the matter's outcome is not settled — the safety gate forces
# ONGOING_AMBIGUOUS whenever one is present, no matter what was proposed.
_AMBIGUOUS_SIGNALS = (
    "ongoing",
    "no findings",
    "unresolved",
    "pending",
    "no resolution",
    "cannot currently be determined",
    "under investigation",
    "no settlement has been reached",
)

# Only consulted when none of the ambiguous signals above are present.
_RESOLVED_SIGNALS = (
    "resolved",
    "dismissed with prejudice",
    "consent agreement",
    "no further obligations",
    "no further exposure",
    "settled",
)

CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "classification": {"type": "string", "enum": [RESOLVED_IMMATERIAL, ONGOING_AMBIGUOUS]},
    },
    "required": ["classification"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class AdverseMediaRecord:
    record_id: int
    title: str
    subject: str
    filed_year: int
    status_text: str
    summary: str
    citation: dict[str, Any]

    @property
    def full_text(self) -> str:
        return f"{self.status_text} {self.summary}"


@dataclass(frozen=True)
class ClassifiedAdverseMediaRecord:
    record: AdverseMediaRecord
    classification: str  # RESOLVED_IMMATERIAL | ONGOING_AMBIGUOUS
    human_review: bool
    classification_source: str  # "llm" | "fallback_keyword"
    safety_gate_overrode: bool
    rationale: str


_RECORD_HEADER = re.compile(r"^## Record (\d+)\. (.+)$")
_SUBJECT_LINE = re.compile(r"^\*\*Subject:\*\* (.+)$")
_FILED_STATUS_LINE = re.compile(r"^\*\*Filed:\*\* (\d{4}) \*\*Status:\*\* (.+)$")
_SUMMARY_LINE = re.compile(r"^\*\*Summary:\*\* (.+)$")


def extract_adverse_media_records(path: str | Path) -> list[AdverseMediaRecord]:
    """Parse adverse_media_records.md into structured, cited records."""
    document = Path(path).name
    lines = Path(path).read_text().splitlines()

    records: list[AdverseMediaRecord] = []
    index = 0
    while index < len(lines):
        header_match = _RECORD_HEADER.match(lines[index])
        if not header_match:
            index += 1
            continue

        record_id, title = int(header_match.group(1)), header_match.group(2)
        header_line = index + 1
        subject = filed_year = status_text = summary = None
        index += 1

        while index < len(lines) and not _RECORD_HEADER.match(lines[index]):
            line = lines[index]
            if subject_match := _SUBJECT_LINE.match(line):
                subject = subject_match.group(1)
            elif filed_status_match := _FILED_STATUS_LINE.match(line):
                filed_year = int(filed_status_match.group(1))
                status_text = filed_status_match.group(2)
            elif summary_match := _SUMMARY_LINE.match(line):
                summary = summary_match.group(1)
            index += 1

        if subject is None or filed_year is None or status_text is None or summary is None:
            raise ValueError(f"Incomplete adverse media record #{record_id} in {document}")

        records.append(
            AdverseMediaRecord(
                record_id=record_id,
                title=title,
                subject=subject,
                filed_year=filed_year,
                status_text=status_text,
                summary=summary,
                citation={"document": document, "line": header_line},
            )
        )

    return records


def classify_record_with_llm(record: AdverseMediaRecord) -> str | None:
    """Classify via a live Claude call, or return None if unavailable.

    Mirrors creditpulse.memo_drafter.draft_memo_claims: callers fall back to
    a deterministic classifier when this returns None (no API key, or the
    call/parse fails). Either way, the caller still applies the structural
    safety gate afterward — this function's output is never trusted as-is.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    import anthropic  # deferred: only required when a live call is possible

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=CLASSIFICATION_MODEL,
            max_tokens=200,
            output_config={
                "format": {"type": "json_schema", "schema": CLASSIFICATION_SCHEMA},
                "effort": "low",
            },
            messages=[{"role": "user", "content": _build_prompt(record)}],
        )
    except Exception:
        return None

    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        return None

    try:
        classification = json.loads(text)["classification"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

    if classification not in (RESOLVED_IMMATERIAL, ONGOING_AMBIGUOUS):
        return None
    return classification


def classify_record_fallback(record: AdverseMediaRecord) -> str:
    """Deterministic keyword classifier, used when no live LLM call is available.

    Checked in order: any ambiguous signal wins first (never let a resolved
    keyword mask genuinely unresolved language); only if none are present do
    resolved signals apply; if neither list matches, default to
    ONGOING_AMBIGUOUS — an unrecognized record is routed to human review,
    never assumed clean.
    """
    text = record.full_text.lower()
    if any(signal in text for signal in _AMBIGUOUS_SIGNALS):
        return ONGOING_AMBIGUOUS
    if any(signal in text for signal in _RESOLVED_SIGNALS):
        return RESOLVED_IMMATERIAL
    return ONGOING_AMBIGUOUS


def apply_safety_gate(record: AdverseMediaRecord, proposed_classification: str) -> tuple[str, bool]:
    """Structural backstop, applied after any classification (LLM or fallback).

    If the record's own text contains a clear unresolved signal, the result
    is forced to ONGOING_AMBIGUOUS regardless of what was proposed. This is
    the guarantee that an ambiguous item is never auto-classified as clean
    — enforced in code, not left to prompting alone.
    """
    text = record.full_text.lower()
    if any(signal in text for signal in _AMBIGUOUS_SIGNALS) and proposed_classification != ONGOING_AMBIGUOUS:
        return ONGOING_AMBIGUOUS, True
    return proposed_classification, False


def classify_records(records: list[AdverseMediaRecord]) -> list[ClassifiedAdverseMediaRecord]:
    """Classify every record, always through the structural safety gate."""
    classified = []
    for record in records:
        llm_result = classify_record_with_llm(record)
        if llm_result is not None:
            proposed, source = llm_result, "llm"
        else:
            proposed, source = classify_record_fallback(record), "fallback_keyword"

        final_classification, overrode = apply_safety_gate(record, proposed)
        rationale = (
            f"Safety gate overrode a proposed '{proposed}' classification because the record's own text "
            "contains unresolved language." if overrode else f"Classified '{final_classification}' via {source}, confirmed by the safety gate."
        )
        classified.append(
            ClassifiedAdverseMediaRecord(
                record=record,
                classification=final_classification,
                human_review=final_classification == ONGOING_AMBIGUOUS,
                classification_source=source,
                safety_gate_overrode=overrode,
                rationale=rationale,
            )
        )
    return classified


def _build_prompt(record: AdverseMediaRecord) -> str:
    return (
        "You are classifying a single adverse media / legal record for a private-credit sponsor "
        "diligence review. Classify it as exactly one of:\n"
        f"- \"{RESOLVED_IMMATERIAL}\": the matter is closed, with a stated resolution and no remaining exposure.\n"
        f"- \"{ONGOING_AMBIGUOUS}\": the matter is unresolved, ongoing, or its outcome cannot yet be determined.\n\n"
        "If you are not confident the matter is fully and finally resolved, classify it as "
        f"\"{ONGOING_AMBIGUOUS}\" — do not guess toward a clean result. Base your classification "
        "only on the record text below, nothing else.\n\n"
        f"Title: {record.title}\n"
        f"Subject: {record.subject}\n"
        f"Filed: {record.filed_year}\n"
        f"Status: {record.status_text}\n"
        f"Summary: {record.summary}\n"
    )
