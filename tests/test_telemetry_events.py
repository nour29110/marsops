"""Tests for marsops.telemetry.events: TelemetryEvent and MissionLog."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from marsops.telemetry.events import MissionLog, TelemetryEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_EVENT_TYPES = [
    "step",
    "waypoint_reached",
    "low_battery",
    "mission_start",
    "mission_complete",
    "mission_failed",
]


def _make_event(
    *,
    timestamp_s: float = 0.0,
    event_type: str = "step",
    position: tuple[int, int] = (0, 0),
    battery_pct: float = 100.0,
    elevation_m: float = -2600.0,
    heading_deg: float = 0.0,
    message: str = "test",
) -> TelemetryEvent:
    return TelemetryEvent(
        timestamp_s=timestamp_s,
        event_type=event_type,  # type: ignore[arg-type]
        position=position,
        battery_pct=battery_pct,
        elevation_m=elevation_m,
        heading_deg=heading_deg,
        message=message,
    )


# ---------------------------------------------------------------------------
# TelemetryEvent construction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event_type", _VALID_EVENT_TYPES)
def test_telemetry_event_constructs(event_type: str) -> None:
    """TelemetryEvent constructs with all required fields for every valid event type."""
    event = _make_event(event_type=event_type)
    assert event.event_type == event_type
    assert event.timestamp_s == 0.0
    assert event.position == (0, 0)
    assert event.battery_pct == 100.0
    assert event.elevation_m == -2600.0
    assert event.heading_deg == 0.0
    assert event.message == "test"


def test_telemetry_event_stores_all_fields() -> None:
    """TelemetryEvent stores every supplied field accurately."""
    event = TelemetryEvent(
        timestamp_s=42.5,
        event_type="waypoint_reached",
        position=(3, 7),
        battery_pct=55.3,
        elevation_m=-2580.0,
        heading_deg=270.0,
        message="custom",
    )
    assert event.timestamp_s == 42.5
    assert event.position == (3, 7)
    assert event.battery_pct == 55.3
    assert event.elevation_m == -2580.0
    assert event.heading_deg == 270.0
    assert event.message == "custom"


# ---------------------------------------------------------------------------
# MissionLog.duration_s
# ---------------------------------------------------------------------------


def test_duration_s_multiple_events() -> None:
    """duration_s returns last minus first timestamp for a multi-event log."""
    events = [
        _make_event(timestamp_s=10.0),
        _make_event(timestamp_s=20.0),
        _make_event(timestamp_s=35.0),
    ]
    log = MissionLog(events=events)
    assert log.duration_s() == pytest.approx(25.0)


def test_duration_s_single_event() -> None:
    """duration_s returns 0.0 for a single-event log."""
    log = MissionLog(events=[_make_event(timestamp_s=99.9)])
    assert log.duration_s() == 0.0


def test_duration_s_empty_log() -> None:
    """duration_s returns 0.0 for an empty log."""
    log = MissionLog(events=[])
    assert log.duration_s() == 0.0


# ---------------------------------------------------------------------------
# MissionLog.distance_cells
# ---------------------------------------------------------------------------


def test_distance_cells_counts_only_step_events() -> None:
    """distance_cells counts only 'step' events, ignoring all others."""
    events = [
        _make_event(event_type="mission_start"),
        _make_event(event_type="step"),
        _make_event(event_type="waypoint_reached"),
        _make_event(event_type="step"),
        _make_event(event_type="low_battery"),
        _make_event(event_type="step"),
        _make_event(event_type="mission_complete"),
    ]
    log = MissionLog(events=events)
    assert log.distance_cells() == 3


def test_distance_cells_no_steps() -> None:
    """distance_cells returns 0 when no step events are present."""
    events = [
        _make_event(event_type="mission_start"),
        _make_event(event_type="mission_complete"),
    ]
    log = MissionLog(events=events)
    assert log.distance_cells() == 0


# ---------------------------------------------------------------------------
# MissionLog.waypoints_reached
# ---------------------------------------------------------------------------


def test_waypoints_reached_counts_only_waypoint_events() -> None:
    """waypoints_reached counts only 'waypoint_reached' events."""
    events = [
        _make_event(event_type="mission_start"),
        _make_event(event_type="step"),
        _make_event(event_type="waypoint_reached"),
        _make_event(event_type="step"),
        _make_event(event_type="waypoint_reached"),
        _make_event(event_type="mission_complete"),
    ]
    log = MissionLog(events=events)
    assert log.waypoints_reached() == 2


def test_waypoints_reached_zero() -> None:
    """waypoints_reached returns 0 when no waypoint events are present."""
    log = MissionLog(events=[_make_event(event_type="step")])
    assert log.waypoints_reached() == 0


# ---------------------------------------------------------------------------
# MissionLog.final_battery
# ---------------------------------------------------------------------------


def test_final_battery_returns_last_event_battery() -> None:
    """final_battery returns the last event's battery_pct."""
    events = [
        _make_event(battery_pct=100.0),
        _make_event(battery_pct=80.0),
        _make_event(battery_pct=42.7),
    ]
    log = MissionLog(events=events)
    assert log.final_battery() == pytest.approx(42.7)


def test_final_battery_empty_log_returns_100() -> None:
    """final_battery returns 100.0 for an empty log."""
    log = MissionLog(events=[])
    assert log.final_battery() == 100.0


# ---------------------------------------------------------------------------
# JSONL round-trip
# ---------------------------------------------------------------------------


def test_to_jsonl_from_jsonl_round_trip(tmp_path: Path) -> None:
    """to_jsonl then from_jsonl reconstructs an equal MissionLog."""
    events = [
        _make_event(timestamp_s=0.0, event_type="mission_start"),
        _make_event(timestamp_s=10.0, event_type="step", battery_pct=95.0),
        _make_event(timestamp_s=20.0, event_type="waypoint_reached", battery_pct=90.0),
        _make_event(timestamp_s=30.0, event_type="mission_complete", battery_pct=85.0),
    ]
    original = MissionLog(events=events)

    jsonl_path = tmp_path / "mission.jsonl"
    original.to_jsonl(jsonl_path)
    loaded = MissionLog.from_jsonl(jsonl_path)

    assert len(loaded.events) == len(original.events)
    for orig_e, loaded_e in zip(original.events, loaded.events, strict=True):
        assert orig_e == loaded_e


def test_from_jsonl_file_not_found(tmp_path: Path) -> None:
    """from_jsonl raises FileNotFoundError for a missing path."""
    with pytest.raises(FileNotFoundError):
        MissionLog.from_jsonl(tmp_path / "nonexistent.jsonl")


def test_to_jsonl_creates_parent_dirs(tmp_path: Path) -> None:
    """to_jsonl creates parent directories when they do not exist."""
    nested_path = tmp_path / "a" / "b" / "c" / "log.jsonl"
    log = MissionLog(events=[_make_event()])
    log.to_jsonl(nested_path)
    assert nested_path.exists()


def test_from_jsonl_raises_value_error_on_malformed_line(tmp_path: Path) -> None:
    """from_jsonl raises ValueError when a line cannot be parsed as TelemetryEvent."""
    bad_jsonl = tmp_path / "bad.jsonl"
    bad_jsonl.write_text("this is not valid json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Failed to parse line"):
        MissionLog.from_jsonl(bad_jsonl)


def test_from_jsonl_skips_blank_lines(tmp_path: Path) -> None:
    """from_jsonl silently skips blank lines and still loads valid events."""
    event = _make_event(timestamp_s=5.0, event_type="step")
    jsonl_path = tmp_path / "with_blanks.jsonl"
    # Write a blank line before and after the valid event line
    jsonl_path.write_text(
        "\n" + event.model_dump_json() + "\n\n",
        encoding="utf-8",
    )
    loaded = MissionLog.from_jsonl(jsonl_path)
    assert len(loaded.events) == 1
    assert loaded.events[0] == event


# ---------------------------------------------------------------------------
# Hypothesis property-based tests
# ---------------------------------------------------------------------------

_event_type_st = st.sampled_from(
    [
        "step",
        "waypoint_reached",
        "low_battery",
        "mission_start",
        "mission_complete",
        "mission_failed",
    ]
)

_event_st = st.builds(
    TelemetryEvent,
    timestamp_s=st.floats(
        min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False
    ),
    event_type=_event_type_st,
    position=st.tuples(st.integers(0, 99), st.integers(0, 99)),
    battery_pct=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    elevation_m=st.floats(
        min_value=-5000.0, max_value=5000.0, allow_nan=False, allow_infinity=False
    ),
    heading_deg=st.floats(min_value=0.0, max_value=360.0, allow_nan=False, allow_infinity=False),
    message=st.text(min_size=0, max_size=200),
)


@given(events=st.lists(_event_st, min_size=1, max_size=20))
@settings(max_examples=100, deadline=500)
def test_hypothesis_duration_s(events: list[TelemetryEvent]) -> None:
    """For any list of 1-20 events, duration_s equals last minus first timestamp."""
    log = MissionLog(events=events)
    expected = events[-1].timestamp_s - events[0].timestamp_s if len(events) >= 2 else 0.0
    assert log.duration_s() == pytest.approx(expected, abs=1e-9)


@given(events=st.lists(_event_st, min_size=1, max_size=20))
@settings(max_examples=100, deadline=500)
def test_hypothesis_distance_cells(events: list[TelemetryEvent]) -> None:
    """For any list of 1-20 events, distance_cells equals number of 'step' events."""
    log = MissionLog(events=events)
    expected_steps = sum(1 for e in events if e.event_type == "step")
    assert log.distance_cells() == expected_steps
