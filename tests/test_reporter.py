"""Tests for marsops.telemetry.reporter: generate_mission_report."""

from __future__ import annotations

from pathlib import Path

import pytest

from marsops.telemetry.events import MissionLog, TelemetryEvent
from marsops.telemetry.reporter import _outcome, _recommendation, generate_mission_report

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TERRAIN_NAME = "Test Terrain"


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


def _success_log(final_battery: float = 80.0) -> MissionLog:
    """Build a minimal mission_start → step → mission_complete log."""
    return MissionLog(
        events=[
            _make_event(timestamp_s=0.0, event_type="mission_start", battery_pct=100.0),
            _make_event(timestamp_s=10.0, event_type="step", battery_pct=95.0),
            _make_event(timestamp_s=20.0, event_type="mission_complete", battery_pct=final_battery),
        ]
    )


def _failure_log() -> MissionLog:
    """Build a mission_start → step → mission_failed log."""
    return MissionLog(
        events=[
            _make_event(timestamp_s=0.0, event_type="mission_start", battery_pct=100.0),
            _make_event(timestamp_s=5.0, event_type="step", battery_pct=50.0),
            _make_event(timestamp_s=5.0, event_type="mission_failed", battery_pct=0.0),
        ]
    )


def _partial_log() -> MissionLog:
    """Build a log with neither mission_complete nor mission_failed."""
    return MissionLog(
        events=[
            _make_event(timestamp_s=0.0, event_type="mission_start", battery_pct=100.0),
            _make_event(timestamp_s=5.0, event_type="step", battery_pct=50.0),
        ]
    )


# ---------------------------------------------------------------------------
# _outcome helper
# ---------------------------------------------------------------------------


def test_outcome_success() -> None:
    """_outcome returns 'success' when mission_complete is present."""
    assert _outcome(_success_log()) == "success"


def test_outcome_failure() -> None:
    """_outcome returns 'failure' when mission_failed is present."""
    assert _outcome(_failure_log()) == "failure"


def test_outcome_partial() -> None:
    """_outcome returns 'partial' when neither terminal event is present."""
    assert _outcome(_partial_log()) == "partial"


# ---------------------------------------------------------------------------
# _recommendation helper
# ---------------------------------------------------------------------------


def test_recommendation_continue_high_battery() -> None:
    """_recommendation returns Continue when mission succeeds with battery > 40 %."""
    log = _success_log(final_battery=80.0)
    rec = _recommendation(log)
    assert "Continue" in rec
    assert "\U0001f7e2" in rec  # 🟢


def test_recommendation_return_low_battery_success() -> None:
    """_recommendation returns Return to base when successful but battery 20-40 %."""
    log = _success_log(final_battery=30.0)
    rec = _recommendation(log)
    assert "Return to base" in rec
    assert "\U0001f7e1" in rec  # 🟡


def test_recommendation_abort_on_failure() -> None:
    """_recommendation returns Abort when mission_failed event is present."""
    rec = _recommendation(_failure_log())
    assert "Abort" in rec
    assert "\U0001f534" in rec  # 🔴


def test_recommendation_abort_critical_battery() -> None:
    """_recommendation returns Abort when battery is critically low (< 20 %)."""
    log = _success_log(final_battery=10.0)
    rec = _recommendation(log)
    assert "Abort" in rec
    assert "\U0001f534" in rec  # 🔴


def test_recommendation_return_partial() -> None:
    """_recommendation returns Return to base when mission is partial."""
    rec = _recommendation(_partial_log())
    assert "Return to base" in rec


# ---------------------------------------------------------------------------
# generate_mission_report — file creation
# ---------------------------------------------------------------------------


def test_generate_report_creates_file(tmp_path: Path) -> None:
    """generate_mission_report writes a file to the given path."""
    out = tmp_path / "report.md"
    generate_mission_report(_success_log(), _TERRAIN_NAME, out)
    assert out.exists()
    assert out.stat().st_size > 0


def test_generate_report_returns_path(tmp_path: Path) -> None:
    """generate_mission_report returns the resolved output path."""
    out = tmp_path / "report.md"
    result = generate_mission_report(_success_log(), _TERRAIN_NAME, out)
    assert result == out.resolve()


def test_generate_report_creates_parent_dirs(tmp_path: Path) -> None:
    """generate_mission_report creates parent directories automatically."""
    nested = tmp_path / "a" / "b" / "report.md"
    assert not nested.parent.exists()
    generate_mission_report(_success_log(), _TERRAIN_NAME, nested)
    assert nested.exists()


# ---------------------------------------------------------------------------
# generate_mission_report — content spot-checks
# ---------------------------------------------------------------------------


def test_report_contains_terrain_name(tmp_path: Path) -> None:
    """Report body includes the terrain name passed as argument."""
    out = tmp_path / "r.md"
    generate_mission_report(_success_log(), "My Terrain XYZ", out)
    content = out.read_text(encoding="utf-8")
    assert "My Terrain XYZ" in content


def test_report_contains_mission_summary_heading(tmp_path: Path) -> None:
    """Report contains a '## Mission Summary' heading."""
    out = tmp_path / "r.md"
    generate_mission_report(_success_log(), _TERRAIN_NAME, out)
    assert "## Mission Summary" in out.read_text(encoding="utf-8")


def test_report_contains_key_metrics_heading(tmp_path: Path) -> None:
    """Report contains a '## Key Metrics' heading."""
    out = tmp_path / "r.md"
    generate_mission_report(_success_log(), _TERRAIN_NAME, out)
    assert "## Key Metrics" in out.read_text(encoding="utf-8")


def test_report_contains_timeline_heading(tmp_path: Path) -> None:
    """Report contains a '## Timeline of Notable Events' heading."""
    out = tmp_path / "r.md"
    generate_mission_report(_success_log(), _TERRAIN_NAME, out)
    assert "## Timeline of Notable Events" in out.read_text(encoding="utf-8")


def test_report_contains_anomalies_heading(tmp_path: Path) -> None:
    """Report contains an '## Anomalies' heading."""
    out = tmp_path / "r.md"
    generate_mission_report(_success_log(), _TERRAIN_NAME, out)
    assert "## Anomalies" in out.read_text(encoding="utf-8")


def test_report_contains_recommendation_heading(tmp_path: Path) -> None:
    """Report contains a '## Recommendation' heading."""
    out = tmp_path / "r.md"
    generate_mission_report(_success_log(), _TERRAIN_NAME, out)
    assert "## Recommendation" in out.read_text(encoding="utf-8")


def test_report_no_anomalies_section_text(tmp_path: Path) -> None:
    """Successful mission with no anomalies writes 'No anomalies detected.'"""
    out = tmp_path / "r.md"
    generate_mission_report(_success_log(), _TERRAIN_NAME, out)
    assert "No anomalies detected." in out.read_text(encoding="utf-8")


def test_report_failure_anomalies_present(tmp_path: Path) -> None:
    """Failed mission lists the mission_failed event in anomalies section."""
    out = tmp_path / "r.md"
    generate_mission_report(_failure_log(), _TERRAIN_NAME, out)
    content = out.read_text(encoding="utf-8")
    assert "mission_failed" in content


def test_report_waypoint_in_timeline(tmp_path: Path) -> None:
    """A log with a waypoint_reached event has it in the timeline section."""
    log = MissionLog(
        events=[
            _make_event(timestamp_s=0.0, event_type="mission_start", battery_pct=100.0),
            _make_event(timestamp_s=5.0, event_type="step", battery_pct=99.0),
            _make_event(
                timestamp_s=10.0,
                event_type="waypoint_reached",
                battery_pct=98.0,
                message="Waypoint reached: (1, 1)",
            ),
            _make_event(timestamp_s=20.0, event_type="mission_complete", battery_pct=80.0),
        ]
    )
    out = tmp_path / "r.md"
    generate_mission_report(log, _TERRAIN_NAME, out)
    assert "waypoint_reached" in out.read_text(encoding="utf-8")


def test_report_low_battery_anomaly(tmp_path: Path) -> None:
    """A log with a low_battery event lists it in the anomalies section."""
    log = MissionLog(
        events=[
            _make_event(timestamp_s=0.0, event_type="mission_start", battery_pct=100.0),
            _make_event(timestamp_s=5.0, event_type="step", battery_pct=15.0),
            _make_event(
                timestamp_s=5.0,
                event_type="low_battery",
                battery_pct=15.0,
                message="Low battery: 15.0% at (0, 0)",
            ),
            _make_event(timestamp_s=20.0, event_type="mission_complete", battery_pct=10.0),
        ]
    )
    out = tmp_path / "r.md"
    generate_mission_report(log, _TERRAIN_NAME, out)
    assert "low_battery" in out.read_text(encoding="utf-8")


def test_report_distances_from_log(tmp_path: Path) -> None:
    """Distance in report equals log.distance_cells()."""
    log = _success_log()
    out = tmp_path / "r.md"
    generate_mission_report(log, _TERRAIN_NAME, out)
    content = out.read_text(encoding="utf-8")
    expected_dist = str(log.distance_cells())
    assert expected_dist in content


def test_report_idempotent(tmp_path: Path) -> None:
    """Calling generate_mission_report twice produces identical output."""
    log = _success_log()
    out1 = tmp_path / "r1.md"
    out2 = tmp_path / "r2.md"
    generate_mission_report(log, _TERRAIN_NAME, out1)
    generate_mission_report(log, _TERRAIN_NAME, out2)
    assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_report_empty_log(tmp_path: Path) -> None:
    """generate_mission_report handles an empty MissionLog without raising."""
    log = MissionLog(events=[])
    out = tmp_path / "empty.md"
    result = generate_mission_report(log, _TERRAIN_NAME, out)
    assert result.exists()


@pytest.mark.parametrize("battery", [0.0, 19.9, 20.0, 39.9, 40.0, 100.0])
def test_recommendation_battery_boundaries(tmp_path: Path, battery: float) -> None:
    """generate_mission_report does not raise for boundary battery values."""
    log = _success_log(final_battery=battery)
    out = tmp_path / f"b_{battery}.md"
    generate_mission_report(log, _TERRAIN_NAME, out)
    assert out.exists()
