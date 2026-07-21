"""Utilities for working with cited extraction tables."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from creditpulse.policy import ExtractedField


def citation_to_text(citation: dict[str, Any]) -> str:
    """Render a structured citation as compact document provenance text."""
    document = citation["document"]
    if "section" in citation:
        return f"{document} §{citation['section']}"
    if "row" in citation:
        return f"{document} row {citation['row']}"
    return document


def flatten_extraction_table(path: str | Path) -> dict[str, ExtractedField]:
    """Flatten the nested extraction fixture into policy-checkable fields."""
    table = json.loads(Path(path).read_text())
    fields: dict[str, ExtractedField] = {
        "borrower": ExtractedField("borrower", table["borrower"]["value"], citation_to_text(table["borrower"]["citation"])),
    }
    for name, payload in table["covenants"].items():
        fields[name] = ExtractedField(name, payload["value"], citation_to_text(payload["citation"]))
    for name, payload in table["latest_month"].items():
        fields[f"latest_{name}" if name != "month" else "latest_month"] = ExtractedField(
            f"latest_{name}" if name != "month" else "latest_month",
            payload["value"],
            citation_to_text(payload["citation"]),
        )
    return fields
