"""Tests for marsops.web_api.parser — fully deterministic, no LLM."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from marsops.web_api.parser import ParsedCommand, parse_command

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _parse(text: str) -> ParsedCommand:
    return parse_command(text)


# ---------------------------------------------------------------------------
# load_terrain — synthetic (default when "real" is absent)
# ---------------------------------------------------------------------------

LOAD_SYNTHETIC_PHRASINGS = [
    "load terrain",
    "load synthetic terrain",
    "Load the Terrain!",
    "LOAD TERRAIN",
    "load   terrain",
    "please load terrain now",
]


@pytest.mark.parametrize("text", LOAD_SYNTHETIC_PHRASINGS)
def test_load_terrain_synthetic(text: str) -> None:
    cmd = _parse(text)
    assert cmd.intent == "load_terrain"
    assert cmd.args["source"] == "synthetic"
    assert cmd.confidence == 1.0


LOAD_REAL_PHRASINGS = [
    "load real terrain",
    "LOAD REAL TERRAIN",
    "Load Real Terrain",
    "load the real terrain",
]


@pytest.mark.parametrize("text", LOAD_REAL_PHRASINGS)
def test_load_terrain_real(text: str) -> None:
    cmd = _parse(text)
    assert cmd.intent == "load_terrain"
    assert cmd.args["source"] == "real"
    assert cmd.confidence == 1.0


# ---------------------------------------------------------------------------
# get_terrain_info
# ---------------------------------------------------------------------------

TERRAIN_INFO_PHRASINGS = [
    "terrain info",
    "terrain info please",
    "tell me about the terrain",
    "what's the terrain",
    "what's the terrain?",
    "whats the terrain",
    "TERRAIN INFO",
]


@pytest.mark.parametrize("text", TERRAIN_INFO_PHRASINGS)
def test_get_terrain_info(text: str) -> None:
    cmd = _parse(text)
    assert cmd.intent == "get_terrain_info"
    assert cmd.confidence == 1.0


# ---------------------------------------------------------------------------
# plan_mission — coordinates only (default min_waypoints = 2)
# ---------------------------------------------------------------------------


def test_plan_mission_with_coords_and_waypoints() -> None:
    cmd = _parse("plan mission at (10, 20) with 3 waypoints")
    assert cmd.intent == "plan_mission"
    assert cmd.args["start_row"] == 10
    assert cmd.args["start_col"] == 20
    assert cmd.args["min_waypoints"] == 3
    assert cmd.confidence == 1.0


def test_plan_mission_short_form_default_waypoints() -> None:
    cmd = _parse("plan a mission 5, 7")
    assert cmd.intent == "plan_mission"
    assert cmd.args["start_row"] == 5
    assert cmd.args["start_col"] == 7
    assert cmd.args["min_waypoints"] == 2  # default


def test_plan_mission_description_field_present() -> None:
    cmd = _parse("plan mission at (10, 20) with 3 waypoints")
    assert "description" in cmd.args
    assert isinstance(cmd.args["description"], str)


# ---------------------------------------------------------------------------
# plan_mission — quadrant ROI
# ---------------------------------------------------------------------------

QUADRANT_CASES = [
    # (phrase, roi_row_min, roi_col_min, roi_row_max, roi_col_max)
    ("NW", 0, 0, 50, 50),
    ("NE", 0, 50, 50, 100),
    ("SW", 50, 0, 100, 50),
    ("SE", 50, 50, 100, 100),
    ("northwest", 0, 0, 50, 50),
    ("northeast", 0, 50, 50, 100),
    ("southwest", 50, 0, 100, 50),
    ("southeast", 50, 50, 100, 100),
]


@pytest.mark.parametrize("quad,rmin,cmin,rmax,cmax", QUADRANT_CASES)
def test_plan_mission_quadrant(quad: str, rmin: int, cmin: int, rmax: int, cmax: int) -> None:
    cmd = _parse(f"plan mission at (10, 20) with 3 waypoints in the {quad} quadrant")
    assert cmd.intent == "plan_mission"
    assert cmd.args["roi_row_min"] == rmin
    assert cmd.args["roi_col_min"] == cmin
    assert cmd.args["roi_row_max"] == rmax
    assert cmd.args["roi_col_max"] == cmax


def test_plan_mission_no_quadrant_has_no_roi_keys() -> None:
    cmd = _parse("plan mission at (10, 20) with 3 waypoints")
    assert "roi_row_min" not in cmd.args
    assert "roi_col_min" not in cmd.args
    assert "roi_row_max" not in cmd.args
    assert "roi_col_max" not in cmd.args


# ---------------------------------------------------------------------------
# execute_mission
# ---------------------------------------------------------------------------

EXECUTE_PHRASINGS = [
    "execute mission",
    "run mission",
    "go",
    "Execute!",
    "run",
    "execute",
    "Execute Mission",
    "RUN MISSION",
]


@pytest.mark.parametrize("text", EXECUTE_PHRASINGS)
def test_execute_mission(text: str) -> None:
    cmd = _parse(text)
    assert cmd.intent == "execute_mission"
    assert cmd.confidence == 1.0


# ---------------------------------------------------------------------------
# inject_anomaly — dust storm
# ---------------------------------------------------------------------------

DUST_PHRASINGS = [
    "inject a dust storm",
    "inject dust storm",
    "inject dust storm now",
]


@pytest.mark.parametrize("text", DUST_PHRASINGS)
def test_inject_dust_storm_default_step(text: str) -> None:
    cmd = _parse(text)
    assert cmd.intent == "inject_anomaly"
    assert cmd.args["anomaly_type"] == "dust_storm"
    assert cmd.args["trigger_at_step"] == 3  # default
    assert cmd.args["severity"] == 0.6
    assert cmd.confidence == 1.0


def test_inject_dust_storm_custom_step() -> None:
    cmd = _parse("inject dust storm at step 5")
    assert cmd.intent == "inject_anomaly"
    assert cmd.args["anomaly_type"] == "dust_storm"
    assert cmd.args["trigger_at_step"] == 5


# ---------------------------------------------------------------------------
# inject_anomaly — wheel stuck
# ---------------------------------------------------------------------------


def test_inject_wheel_stuck_default_step() -> None:
    cmd = _parse("inject a wheel stuck")
    assert cmd.intent == "inject_anomaly"
    assert cmd.args["anomaly_type"] == "wheel_stuck"
    assert cmd.args["trigger_at_step"] == 3
    assert cmd.args["blocked_cells"] == [[16, 16], [17, 17], [18, 18]]


def test_inject_wheel_stuck_custom_step() -> None:
    cmd = _parse("inject a wheel stuck at step 2")
    assert cmd.intent == "inject_anomaly"
    assert cmd.args["anomaly_type"] == "wheel_stuck"
    assert cmd.args["trigger_at_step"] == 2
    assert cmd.args["blocked_cells"] == [[16, 16], [17, 17], [18, 18]]


# ---------------------------------------------------------------------------
# inject_anomaly — thermal alert
# ---------------------------------------------------------------------------

THERMAL_PHRASINGS = [
    "inject thermal alert",
    "inject a thermal alert",
    "inject thermal alert now",
]


@pytest.mark.parametrize("text", THERMAL_PHRASINGS)
def test_inject_thermal_alert_default_step(text: str) -> None:
    cmd = _parse(text)
    assert cmd.intent == "inject_anomaly"
    assert cmd.args["anomaly_type"] == "thermal_alert"
    assert cmd.args["trigger_at_step"] == 3
    assert cmd.confidence == 1.0


def test_inject_thermal_alert_custom_step() -> None:
    cmd = _parse("inject a thermal alert at step 0")
    assert cmd.intent == "inject_anomaly"
    assert cmd.args["anomaly_type"] == "thermal_alert"
    assert cmd.args["trigger_at_step"] == 0


# ---------------------------------------------------------------------------
# get_report
# ---------------------------------------------------------------------------

REPORT_PHRASINGS = [
    "show report",
    "get report",
    "what happened",
    "mission report",
    "show mission report",
    "get mission report",
]


@pytest.mark.parametrize("text", REPORT_PHRASINGS)
def test_get_report(text: str) -> None:
    cmd = _parse(text)
    assert cmd.intent == "get_report"
    assert cmd.confidence == 1.0


# ---------------------------------------------------------------------------
# help
# ---------------------------------------------------------------------------

HELP_PHRASINGS = [
    "help",
    "what can you do",
    "commands",
    "HELP",
    "Help!",
]


@pytest.mark.parametrize("text", HELP_PHRASINGS)
def test_help(text: str) -> None:
    cmd = _parse(text)
    assert cmd.intent == "help"
    assert isinstance(cmd.args.get("available"), list)
    assert len(cmd.args["available"]) > 0
    assert cmd.confidence == 1.0


# ---------------------------------------------------------------------------
# unknown
# ---------------------------------------------------------------------------

UNKNOWN_PHRASINGS = [
    "xyzzy",
    "frobnicate the rover",
    "abracadabra",
    "do the magic thing",
]


@pytest.mark.parametrize("text", UNKNOWN_PHRASINGS)
def test_unknown_intent(text: str) -> None:
    cmd = _parse(text)
    assert cmd.intent == "unknown"
    assert cmd.confidence == 0.0
    assert cmd.clarification is not None
    assert isinstance(cmd.clarification, str)
    assert len(cmd.clarification) > 0


def test_unknown_clarification_not_none_and_is_str() -> None:
    cmd = _parse("totally incomprehensible text ZZZZZ")
    assert isinstance(cmd.clarification, str)


def test_closest_hint_dust_in_text_suggests_something() -> None:
    """Ensure closest-hint suggestion for 'dust' doesn't crash and returns str."""
    cmd = _parse("what happened to the dust")
    # This phrase matches get_report ("what happened"), so intent should be get_report
    # If not, it should be unknown with a non-None clarification
    assert cmd.intent in ("get_report", "unknown")
    if cmd.intent == "unknown":
        assert isinstance(cmd.clarification, str)


# ---------------------------------------------------------------------------
# ParsedCommand model properties
# ---------------------------------------------------------------------------


def test_parsed_command_default_confidence() -> None:
    cmd = ParsedCommand(intent="help", args={"available": ["load terrain"]})
    assert cmd.confidence == 1.0


def test_parsed_command_default_clarification_none() -> None:
    cmd = ParsedCommand(intent="execute_mission")
    assert cmd.clarification is None


def test_parsed_command_default_args_empty() -> None:
    cmd = ParsedCommand(intent="execute_mission")
    assert cmd.args == {}


def test_parsed_command_unknown_fields() -> None:
    cmd = ParsedCommand(intent="unknown", confidence=0.0, clarification="try help")
    assert cmd.intent == "unknown"
    assert cmd.confidence == 0.0
    assert cmd.clarification == "try help"


# ---------------------------------------------------------------------------
# Hypothesis — property-based: parse_command must never raise
# ---------------------------------------------------------------------------


@given(st.text(max_size=200))
@settings(max_examples=200, deadline=500)
def test_parse_command_never_raises(text: str) -> None:
    """parse_command must not raise for any string input."""
    result = parse_command(text)
    assert result.intent in (
        "load_terrain",
        "get_terrain_info",
        "plan_mission",
        "execute_mission",
        "inject_anomaly",
        "get_report",
        "help",
        "unknown",
    )


@given(st.text(max_size=200))
@settings(max_examples=200, deadline=500)
def test_parse_command_confidence_in_range(text: str) -> None:
    """confidence must always be 0.0 or 1.0."""
    result = parse_command(text)
    assert result.confidence in (0.0, 1.0)


@given(st.text(max_size=200))
@settings(max_examples=200, deadline=500)
def test_unknown_always_has_clarification(text: str) -> None:
    """When intent is unknown, clarification must be a non-None string."""
    result = parse_command(text)
    if result.intent == "unknown":
        assert isinstance(result.clarification, str)
        assert len(result.clarification) > 0


# ---------------------------------------------------------------------------
# Edge cases — punctuation / casing tolerance
# ---------------------------------------------------------------------------


def test_load_terrain_with_trailing_exclamation() -> None:
    cmd = _parse("Load the Terrain!")
    assert cmd.intent == "load_terrain"
    assert cmd.args["source"] == "synthetic"


def test_execute_mission_with_exclamation() -> None:
    cmd = _parse("Execute!")
    assert cmd.intent == "execute_mission"


def test_empty_string_returns_unknown() -> None:
    cmd = _parse("")
    assert cmd.intent == "unknown"
    assert cmd.confidence == 0.0


def test_whitespace_only_returns_unknown() -> None:
    cmd = _parse("   ")
    assert cmd.intent == "unknown"
    assert cmd.confidence == 0.0


def test_plan_mission_with_parentheses() -> None:
    cmd = _parse("plan mission at (10, 20) with 3 waypoints")
    assert cmd.args["start_row"] == 10
    assert cmd.args["start_col"] == 20
    assert cmd.args["min_waypoints"] == 3


def test_plan_mission_coordinates_without_parentheses() -> None:
    cmd = _parse("plan a mission 5, 7")
    assert cmd.args["start_row"] == 5
    assert cmd.args["start_col"] == 7


def test_help_has_priority_over_load_terrain() -> None:
    """'help load terrain' should resolve to help (higher priority)."""
    cmd = _parse("help load terrain")
    assert cmd.intent == "help"


def test_help_has_priority_over_terrain_info() -> None:
    """'help terrain info' should resolve to help."""
    cmd = _parse("help terrain info")
    assert cmd.intent == "help"
