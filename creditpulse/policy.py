"""CEL-style policy gates for bounded agent orchestration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractedField:
    name: str
    value: object
    citation: str | None


@dataclass(frozen=True)
class MemoClaim:
    text: str
    field_names: tuple[str, ...]


def extraction_fields_are_cited(fields: list[ExtractedField]) -> bool:
    return all(bool(field.citation) for field in fields)


def memo_claim_is_supported(claim: MemoClaim, fields: dict[str, ExtractedField]) -> bool:
    return all(name in fields and bool(fields[name].citation) for name in claim.field_names)


def render_claim(claim: MemoClaim, fields: dict[str, ExtractedField]) -> str:
    if memo_claim_is_supported(claim, fields):
        return claim.text
    return f"[NEEDS REVIEW] {claim.text}"


def final_memo_allowed(has_breach: bool, human_review_complete: bool) -> bool:
    return not has_breach or human_review_complete
