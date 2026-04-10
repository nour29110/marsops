"""Natural-language command parser for the MarsOps Web API.

Provides a deterministic regex/keyword parser that maps user text to
structured :class:`ParsedCommand` objects.  No LLM is used — all matching
is done with compiled regular expressions and keyword lookups.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel

Intent = Literal[
    "load_terrain",
    "get_terrain_info",
    "plan_mission",
    "execute_mission",
    "inject_anomaly",
    "get_report",
    "reset_session",
    "help",
    "unknown",
]


class ParsedCommand(BaseModel):
    """A structured representation of a parsed natural-language command.

    Attributes:
        intent: The detected command intent.
        args: Key-value arguments extracted from the command text.
        confidence: Parse confidence in [0.0, 1.0]. Always 1.0 for matched
            patterns; 0.0 for unrecognised input.
        clarification: Optional suggestion shown when intent is ``"unknown"``.
    """

    intent: Intent
    args: dict[str, Any] = {}
    confidence: float = 1.0
    clarification: str | None = None


# ---------------------------------------------------------------------------
# Compiled regular expressions (module-level, evaluated once)
# ---------------------------------------------------------------------------

_RE_LOAD_TERRAIN: re.Pattern[str] = re.compile(
    r"\bload\b.*?\bterrain\b",
    re.IGNORECASE,
)

_RE_TERRAIN_INFO: re.Pattern[str] = re.compile(
    r"\bterrain\s+info\b"
    r"|tell\s+me\s+about\s+the\s+terrain"
    r"|what'?s?\s+the\s+terrain",
    re.IGNORECASE,
)

_RE_PLAN_MISSION: re.Pattern[str] = re.compile(
    r"\bplan\s+(?:a\s+)?mission\b"
    r"(?:\s+(?:from|starting\s+at|at))?"
    r"\s*\(?\s*(\d+)\s*,?\s*(\d+)\s*\)?"
    r"(?:\s+(?:with\s+)?(\d+)\s+waypoints?)?",
    re.IGNORECASE,
)

_RE_PLAN_QUADRANT: re.Pattern[str] = re.compile(
    r"\bin\s+(?:the\s+)?"
    r"(NW|NE|SW|SE|northwest|northeast|southwest|southeast)"
    r"(?:\s+quadrant)?\b",
    re.IGNORECASE,
)

_RE_EXECUTE: re.Pattern[str] = re.compile(
    r"\bexecute(?:\s+mission)?\b|\brun(?:\s+mission)?\b|\bgo\b",
    re.IGNORECASE,
)

_RE_INJECT_DUST: re.Pattern[str] = re.compile(
    r"\binject\b.*?\bdust\s+storm\b(?:.*?\bat\s+step\s+(\d+))?",
    re.IGNORECASE,
)

_RE_INJECT_WHEEL: re.Pattern[str] = re.compile(
    r"\binject\b.*?\bwheel\s+stuck\b(?:.*?\bat\s+step\s+(\d+))?",
    re.IGNORECASE,
)

_RE_INJECT_THERMAL: re.Pattern[str] = re.compile(
    r"\binject\b.*?\bthermal\s+alert\b(?:.*?\bat\s+step\s+(\d+))?",
    re.IGNORECASE,
)

_RE_REPORT: re.Pattern[str] = re.compile(
    r"\b(?:show\s+|get\s+)?report\b|\bwhat\s+happened\b|\bmission\s+report\b",
    re.IGNORECASE,
)

_RE_HELP: re.Pattern[str] = re.compile(
    r"\bhelp\b|\bwhat\s+can\s+you\s+do\b|\bcommands\b",
    re.IGNORECASE,
)

# Quadrant name → (row_min, col_min, row_max, col_max) within a 100x100 grid
_QUADRANT_MAP: dict[str, tuple[int, int, int, int]] = {
    "nw": (0, 0, 50, 50),
    "northwest": (0, 0, 50, 50),
    "ne": (0, 50, 50, 100),
    "northeast": (0, 50, 50, 100),
    "sw": (50, 0, 100, 50),
    "southwest": (50, 0, 100, 50),
    "se": (50, 50, 100, 100),
    "southeast": (50, 50, 100, 100),
}

_AVAILABLE_COMMANDS: list[str] = [
    "load [synthetic|real] terrain",
    "terrain info / tell me about the terrain / what's the terrain",
    "plan mission at (ROW, COL) [with N waypoints] [in NW|NE|SW|SE quadrant]",
    "execute mission / run [mission] / go",
    "inject [a] dust storm [at step N]",
    "inject [a] wheel stuck [at step N]",
    "inject [a] thermal alert [at step N]",
    "[show|get] report / mission report / what happened",
    "help / what can you do / commands",
]

# Simple keyword hints used for closest-match suggestions
_KEYWORD_HINTS: list[str] = [
    "load terrain",
    "terrain info",
    "plan mission",
    "execute",
    "run",
    "inject dust",
    "inject wheel",
    "inject thermal",
    "report",
    "help",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _closest_hint(text: str) -> str:
    """Return the closest command hint based on substring matching.

    Iterates over :data:`_KEYWORD_HINTS` and returns a suggestion string for
    the first hint whose component words appear in *text*.  Falls back to a
    generic message if no hint matches.

    Args:
        text: The user input text (already lowercased by the caller).

    Returns:
        A human-readable suggestion string.
    """
    text_lower = text.lower()
    for hint in _KEYWORD_HINTS:
        for word in hint.split():
            if word in text_lower:
                return f"Did you mean '{hint}'? Try 'help' to see all commands."
    return "Command not recognised. Try 'help' to see all available commands."


# ---------------------------------------------------------------------------
# Public parser
# ---------------------------------------------------------------------------


def parse_command(text: str) -> ParsedCommand:
    """Parse a natural-language command string into a :class:`ParsedCommand`.

    Matching is case-insensitive and tolerant of extra punctuation and articles.
    Patterns are tested in priority order; the function returns on the first
    match.  No network calls or LLM inference are performed.

    Args:
        text: Raw user input string.

    Returns:
        A :class:`ParsedCommand` with the detected intent and any extracted
        arguments.
    """
    # Strip leading/trailing whitespace and edge punctuation noise
    clean = text.strip().strip("?.!")

    # --- help (highest priority — catch "what can you do" etc.) ---
    if _RE_HELP.search(clean):
        return ParsedCommand(intent="help", args={"available": _AVAILABLE_COMMANDS})

    # --- terrain info ---
    if _RE_TERRAIN_INFO.search(clean):
        return ParsedCommand(intent="get_terrain_info")

    # --- load terrain ---
    if _RE_LOAD_TERRAIN.search(clean):
        lower = clean.lower()
        source = "real" if "real" in lower else "synthetic"
        return ParsedCommand(intent="load_terrain", args={"source": source})

    # --- plan mission ---
    m_plan = _RE_PLAN_MISSION.search(clean)
    if m_plan:
        start_row = int(m_plan.group(1))
        start_col = int(m_plan.group(2))
        min_waypoints = int(m_plan.group(3)) if m_plan.group(3) else 2
        args: dict[str, Any] = {
            "start_row": start_row,
            "start_col": start_col,
            "min_waypoints": min_waypoints,
            "description": (
                f"plan mission from ({start_row},{start_col}) with {min_waypoints} waypoints"
            ),
        }
        m_quad = _RE_PLAN_QUADRANT.search(clean)
        if m_quad:
            key = m_quad.group(1).lower()
            roi = _QUADRANT_MAP.get(key)
            if roi:
                args["roi_row_min"] = roi[0]
                args["roi_col_min"] = roi[1]
                args["roi_row_max"] = roi[2]
                args["roi_col_max"] = roi[3]
                args["description"] = str(args["description"]) + f" in {key} quadrant"
        return ParsedCommand(intent="plan_mission", args=args)

    # --- execute mission ---
    if _RE_EXECUTE.search(clean):
        return ParsedCommand(intent="execute_mission")

    # --- inject anomalies (dust storm, wheel stuck, thermal alert) ---
    m_dust = _RE_INJECT_DUST.search(clean)
    if m_dust:
        step = int(m_dust.group(1)) if m_dust.group(1) else 3
        return ParsedCommand(
            intent="inject_anomaly",
            args={
                "anomaly_type": "dust_storm",
                "trigger_at_step": step,
                "severity": 0.6,
            },
        )

    m_wheel = _RE_INJECT_WHEEL.search(clean)
    if m_wheel:
        step = int(m_wheel.group(1)) if m_wheel.group(1) else 3
        return ParsedCommand(
            intent="inject_anomaly",
            args={
                "anomaly_type": "wheel_stuck",
                "trigger_at_step": step,
                "blocked_cells": [[16, 16], [17, 17], [18, 18]],
            },
        )

    m_thermal = _RE_INJECT_THERMAL.search(clean)
    if m_thermal:
        step = int(m_thermal.group(1)) if m_thermal.group(1) else 3
        return ParsedCommand(
            intent="inject_anomaly",
            args={
                "anomaly_type": "thermal_alert",
                "trigger_at_step": step,
            },
        )

    # --- report ---
    if _RE_REPORT.search(clean):
        return ParsedCommand(intent="get_report")

    # --- reset session ---
    if re.search(r"\b(reset|clear|new session|start over)\b", clean, re.IGNORECASE):
        return ParsedCommand(intent="reset_session")

    # --- unknown ---
    return ParsedCommand(
        intent="unknown",
        confidence=0.0,
        clarification=_closest_hint(clean),
    )
