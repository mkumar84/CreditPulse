"""Sponsor network graph: structured passthrough + deterministic concentration risk.

investor_network.json is served as-is (nodes/edges, no LLM processing). The
only computation here is a plain graph traversal — set intersection over
board_seat edges — to surface investors who share board seats across
multiple portfolio companies. This is a graph algorithm, not an LLM
judgment call, per CreditPulse_Sponsor_Diligence_PRD.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

# Below this many shared board seats, overlap is unremarkable for a small
# fund's normal portfolio construction; at or above it, it's worth a flag.
CONCENTRATION_THRESHOLD = 2


@dataclass(frozen=True)
class ConcentrationFlag:
    investor_a: str
    investor_b: str
    shared_companies: tuple[str, ...]
    message: str


def load_investor_network(path: str | Path) -> dict[str, Any]:
    """Load investor_network.json as-is — structured data passthrough."""
    return json.loads(Path(path).read_text())


def compute_concentration_flags(network: dict[str, Any]) -> list[ConcentrationFlag]:
    """Flag investor pairs holding board seats at CONCENTRATION_THRESHOLD+ shared companies."""
    names_by_id = {node["id"]: node["name"] for node in network["nodes"]}
    investor_ids = {node["id"] for node in network["nodes"] if node["type"] == "investor"}

    board_companies_by_investor: dict[str, set[str]] = {investor_id: set() for investor_id in investor_ids}
    for edge in network["edges"]:
        if edge["type"] == "board_seat" and edge["source"] in investor_ids:
            board_companies_by_investor[edge["source"]].add(edge["target"])

    flags: list[ConcentrationFlag] = []
    for investor_a, investor_b in combinations(sorted(investor_ids), 2):
        shared = board_companies_by_investor[investor_a] & board_companies_by_investor[investor_b]
        if len(shared) >= CONCENTRATION_THRESHOLD:
            shared_names = tuple(sorted(names_by_id[company_id] for company_id in shared))
            name_a, name_b = names_by_id[investor_a], names_by_id[investor_b]
            flags.append(
                ConcentrationFlag(
                    investor_a=name_a,
                    investor_b=name_b,
                    shared_companies=shared_names,
                    message=f"{name_a} and {name_b} share board seats across {len(shared_names)} portfolio companies: {', '.join(shared_names)}.",
                )
            )
    return flags
