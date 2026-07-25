"""Cited extraction for founder/executive profiles and the cap table.

Mirrors creditpulse.extraction's approach: deterministic parsing of the
version-controlled synthetic source files into structured JSON, with a
document + line citation on every field. No LLM is involved in extraction
itself — ambiguous interpretation is out of scope for this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PriorVenture:
    company: str
    outcome: str
    exit_value_millions: float | None
    founder_equity_pct_at_exit: float | None
    shut_down_no_proceeds: bool
    citation: dict[str, Any]


@dataclass(frozen=True)
class FounderProfile:
    name: str
    title_kind: str  # "Founder" or "Executive", as headed in founder_bios.md
    role: str
    education: str
    bio: str
    prior_ventures: tuple[PriorVenture, ...]
    citation: dict[str, Any]  # citation for the profile's header/name line


_PROFILE_HEADER = re.compile(r"^## (Founder|Executive): (.+)$")
_ROLE_LINE = re.compile(r"^\*\*Role:\*\* (.+)$")
_EDUCATION_LINE = re.compile(r"^\*\*Education:\*\* (.+)$")
_BIO_LINE = re.compile(r"^\*\*Bio:\*\* (.+)$")
_VENTURE_BULLET = re.compile(r"^- \*\*(.+?)\*\* \((.+?)\): (.+)$")
_NO_VENTURES_BULLET = re.compile(r"^- None disclosed\. (.+)$")
_EXIT_VALUE = re.compile(r"for \$(\d+(?:\.\d+)?) million")
_EQUITY_PCT = re.compile(r"disclosed (\d+(?:\.\d+)?)% founder equity stake")
_SHUT_DOWN_NO_PROCEEDS = re.compile(r"shut down .*no proceeds to founders", re.IGNORECASE)


def extract_founder_profiles(path: str | Path) -> list[FounderProfile]:
    """Parse founder_bios.md into structured, cited founder/executive cards."""
    document = Path(path).name
    lines = Path(path).read_text().splitlines()

    profiles: list[FounderProfile] = []
    index = 0
    while index < len(lines):
        header_match = _PROFILE_HEADER.match(lines[index])
        if not header_match:
            index += 1
            continue

        title_kind, name = header_match.group(1), header_match.group(2)
        header_line = index + 1  # 1-indexed
        role = education = bio = None
        ventures: list[PriorVenture] = []
        index += 1

        while index < len(lines) and not _PROFILE_HEADER.match(lines[index]):
            line = lines[index]
            if role_match := _ROLE_LINE.match(line):
                role = role_match.group(1)
            elif education_match := _EDUCATION_LINE.match(line):
                education = education_match.group(1)
            elif bio_match := _BIO_LINE.match(line):
                bio = bio_match.group(1)
            elif venture_match := _VENTURE_BULLET.match(line):
                company, _years, description = venture_match.groups()
                exit_value_match = _EXIT_VALUE.search(description)
                equity_pct_match = _EQUITY_PCT.search(description)
                ventures.append(
                    PriorVenture(
                        company=company,
                        outcome=description,
                        exit_value_millions=float(exit_value_match.group(1)) if exit_value_match else None,
                        founder_equity_pct_at_exit=float(equity_pct_match.group(1)) if equity_pct_match else None,
                        shut_down_no_proceeds=bool(_SHUT_DOWN_NO_PROCEEDS.search(description)),
                        citation={"document": document, "line": index + 1},
                    )
                )
            elif _NO_VENTURES_BULLET.match(line):
                pass  # explicitly no prior ventures; ventures stays empty
            index += 1

        if role is None or education is None or bio is None:
            raise ValueError(f"Incomplete founder profile for {name!r} in {document}")

        profiles.append(
            FounderProfile(
                name=name,
                title_kind=title_kind,
                role=role,
                education=education,
                bio=bio,
                prior_ventures=tuple(ventures),
                citation={"document": document, "line": header_line},
            )
        )

    return profiles


@dataclass(frozen=True)
class CapTableEntry:
    holder: str
    holder_class: str
    fully_diluted_pct: float | None
    pending_ratification: bool
    citation: dict[str, Any]


@dataclass(frozen=True)
class CapTable:
    entries: tuple[CapTableEntry, ...]
    latest_implied_valuation_millions: float
    valuation_citation: dict[str, Any]
    board_seats: tuple[str, ...]
    board_citation: dict[str, Any]

    def entry_for(self, holder_name: str) -> CapTableEntry | None:
        return next((entry for entry in self.entries if holder_name in entry.holder), None)


_CAP_TABLE_ROW = re.compile(r"^\| (.+?) \| (.+?) \| (\d+(?:\.\d+)?)% \|$")
_PENDING_HOLDER = re.compile(r"^(.+?) \(.+?\) has a target equity grant")
_VALUATION_LINE = re.compile(r"post-money valuation of \$(\d+(?:\.\d+)?) million")
_BOARD_LINE = re.compile(r"^Meridian's board has four seats: (.+)\.$")
_BOARD_SPLIT = re.compile(r",\s+(?:and\s+)?")
_TRAILING_PAREN = re.compile(r"\s*\(.*?\)$")


def extract_cap_table(path: str | Path) -> CapTable:
    """Parse cap_table.md into structured, cited ownership/valuation/board data."""
    document = Path(path).name
    lines = Path(path).read_text().splitlines()

    entries: list[CapTableEntry] = []
    valuation: float | None = None
    valuation_citation: dict[str, Any] | None = None
    board_seats: tuple[str, ...] = ()
    board_citation: dict[str, Any] | None = None
    pending_holders: set[str] = set()

    for index, line in enumerate(lines):
        if row_match := _CAP_TABLE_ROW.match(line):
            holder, holder_class, pct = row_match.groups()
            entries.append(
                CapTableEntry(
                    holder=holder,
                    holder_class=holder_class,
                    fully_diluted_pct=float(pct),
                    pending_ratification=False,
                    citation={"document": document, "line": index + 1},
                )
            )
        elif pending_match := _PENDING_HOLDER.search(line):
            pending_holders.add(pending_match.group(1))
            entries.append(
                CapTableEntry(
                    holder=pending_match.group(1),
                    holder_class="Common (pending)",
                    fully_diluted_pct=None,
                    pending_ratification=True,
                    citation={"document": document, "line": index + 1},
                )
            )
        elif valuation_match := _VALUATION_LINE.search(line):
            valuation = float(valuation_match.group(1))
            valuation_citation = {"document": document, "line": index + 1}
        elif board_match := _BOARD_LINE.search(line):
            raw_parts = _BOARD_SPLIT.split(board_match.group(1))
            board_seats = tuple(_TRAILING_PAREN.sub("", part).strip() for part in raw_parts)
            board_citation = {"document": document, "line": index + 1}

    if valuation is None or valuation_citation is None:
        raise ValueError(f"Unable to find latest implied valuation in {document}")
    if board_citation is None:
        raise ValueError(f"Unable to find board composition in {document}")

    return CapTable(
        entries=tuple(entries),
        latest_implied_valuation_millions=valuation,
        valuation_citation=valuation_citation,
        board_seats=board_seats,
        board_citation=board_citation,
    )
