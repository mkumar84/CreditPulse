"""Sponsor network graph: structured passthrough + deterministic concentration risk.

investor_network.json is served as-is (nodes/edges, no LLM processing). The
only computation here is plain graph traversal — set intersection over
board_seat edges for concentration risk, and simple connectivity checks —
never an LLM judgment call, per CreditPulse_Sponsor_Diligence_PRD.md.

Edge types (five, each representing a distinct disclosed fact — never
collapsed into one another):
  - co_founded: founded the company, present or past.
  - current_role: presently holds a role at the company, independent of
    any equity/board disclosure. Added specifically so a current
    non-founder executive with no disclosed cap table stake or board seat
    (e.g. a recent hire) still appears connected to their employer in the
    graph, rather than showing up as an isolated node.
  - board_seat: holds a board seat.
  - invested_in: has invested capital.
  - previously_worked_at: past (not current) employment.
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

# Distinct styling per edge type, for the frontend's graph legend. Every
# edge type gets its own color so none visually collapses into another —
# current_role in particular must read as distinct from co_founded, since
# a person can appear with either (or both) and they mean different things.
EDGE_TYPE_LEGEND = {
    "co_founded": {"label": "Co-founded", "color": "#7C3AED", "line_style": "solid"},
    "current_role": {"label": "Current role", "color": "#F59E0B", "line_style": "solid"},
    "board_seat": {"label": "Board seat", "color": "#2563EB", "line_style": "solid"},
    "invested_in": {"label": "Invested in", "color": "#059669", "line_style": "solid"},
    "previously_worked_at": {"label": "Previously worked at", "color": "#6B7280", "line_style": "dashed"},
}


@dataclass(frozen=True)
class ConcentrationFlag:
    investor_a: str
    investor_b: str
    shared_companies: tuple[str, ...]
    message: str


def load_investor_network(path: str | Path) -> dict[str, Any]:
    """Load investor_network.json as-is — structured data passthrough."""
    return json.loads(Path(path).read_text())


def find_current_people_disconnected_from_company(
    network: dict[str, Any], current_people_by_company: dict[str, set[str]]
) -> list[str]:
    """Detect current-person nodes with zero edges to their current company node.

    current_people_by_company maps a company display name to the set of
    person display names who currently work there — sourced independently
    of this graph (e.g. from founder_extraction.py's parse of
    founder_bios.md), not inferred from the graph's own edges, so this can
    catch a graph that's simply missing an edge rather than restate
    whatever the graph already claims. Returns a list of "Person @ Company"
    strings for every current person with no edge at all connecting them
    to that company node — regardless of edge type, so it doesn't matter
    whether the missing connection would have been current_role,
    co_founded, or anything else.
    """
    id_by_name = {node["name"]: node["id"] for node in network["nodes"]}
    gaps: list[str] = []
    for company_name, person_names in current_people_by_company.items():
        company_id = id_by_name.get(company_name)
        if company_id is None:
            gaps.extend(f"{person_name} @ {company_name} (company node missing)" for person_name in person_names)
            continue
        for person_name in person_names:
            person_id = id_by_name.get(person_name)
            if person_id is None:
                gaps.append(f"{person_name} @ {company_name} (person node missing)")
                continue
            connected = any(
                {edge["source"], edge["target"]} == {person_id, company_id} for edge in network["edges"]
            )
            if not connected:
                gaps.append(f"{person_name} @ {company_name}")
    return gaps


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
