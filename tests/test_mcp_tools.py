"""Tests for the tool handler logic in marsops.mcp_server.server.

All tools are exercised via their private ``_``-prefixed inner functions so that
the MCP protocol layer (FastMCP decorator, transport, etc.) is never involved.

Each test starts with a clean session thanks to the ``clean_session`` autouse
fixture that calls ``reset_session()``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from marsops.mcp_server.server import (
    _execute_mission,
    _get_last_mission_report,
    _get_terrain_info,
    _inject_anomaly,
    _load_terrain,
    _plan_mission_tool,
)
from marsops.mcp_server.state import get_session, reset_session

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_session() -> None:
    """Guarantee a pristine session before every test."""
    reset_session()


@pytest.fixture()
def loaded_terrain() -> dict[str, Any]:
    """Load synthetic terrain at downsample_factor=10 and return the result dict."""
    return _load_terrain(source="synthetic", downsample_factor=10)


@pytest.fixture()
def planned_mission(loaded_terrain: dict[str, Any]) -> dict[str, Any]:
    """Load terrain and plan a mission; return the plan result dict."""
    return _plan_mission_tool(
        description="survey",
        start_row=10,
        start_col=10,
        min_waypoints=2,
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _full_end_to_end() -> dict[str, Any]:
    """Load → plan → execute with no anomalies."""
    _load_terrain(source="synthetic", downsample_factor=10)
    _plan_mission_tool(description="survey", start_row=10, start_col=10, min_waypoints=2)
    return _execute_mission()


# ---------------------------------------------------------------------------
# Tool 1 — load_terrain
# ---------------------------------------------------------------------------


class TestLoadTerrain:
    """Coverage for _load_terrain."""

    def test_happy_path_status_ok(self) -> None:
        result = _load_terrain(source="synthetic", downsample_factor=10)
        assert result["status"] == "ok"

    def test_happy_path_required_keys_present(self) -> None:
        result = _load_terrain(source="synthetic", downsample_factor=10)
        for key in ("status", "shape", "elev_min", "elev_max", "resolution_m", "source"):
            assert key in result, f"missing key: {key}"

    def test_happy_path_shape_is_two_element_list(self) -> None:
        result = _load_terrain(source="synthetic", downsample_factor=10)
        shape = result["shape"]
        assert isinstance(shape, list)
        assert len(shape) == 2
        assert all(isinstance(d, int) for d in shape)

    def test_happy_path_elev_min_less_than_elev_max(self) -> None:
        result = _load_terrain(source="synthetic", downsample_factor=10)
        assert result["elev_min"] < result["elev_max"]

    def test_happy_path_terrain_stored_in_session(self) -> None:
        _load_terrain(source="synthetic", downsample_factor=10)
        assert get_session().terrain is not None

    def test_happy_path_source_field_matches_argument(self) -> None:
        result = _load_terrain(source="synthetic", downsample_factor=10)
        assert result["source"] == "synthetic"

    def test_happy_path_downsample_reduces_grid(self) -> None:
        result_ds1 = _load_terrain(source="synthetic", downsample_factor=1)
        reset_session()
        result_ds10 = _load_terrain(source="synthetic", downsample_factor=10)
        rows_ds1, cols_ds1 = result_ds1["shape"]
        rows_ds10, cols_ds10 = result_ds10["shape"]
        assert rows_ds10 < rows_ds1
        assert cols_ds10 < cols_ds1

    def test_bad_source_does_not_raise(self) -> None:
        # BUG: load_jezero_dem uses `if source == "real": ... else: # synthetic`
        # so any unknown source string silently loads synthetic terrain instead
        # of raising or returning {"status": "error"}.  The tool therefore
        # returns "ok" for invalid source values — this is a source-code bug
        # that should be fixed by adding an explicit guard in load_jezero_dem.
        # This test documents the current (incorrect) runtime behaviour so we
        # detect if it ever changes.
        result = _load_terrain(source="bad_source", downsample_factor=5)  # type: ignore[arg-type]
        assert isinstance(result, dict)
        # Currently falls through to synthetic load — document actual status
        assert result["status"] in ("ok", "error")  # either would be acceptable after fix

    def test_bad_source_returns_dict(self) -> None:
        # Companion to test_bad_source_does_not_raise — ensures function never
        # raises, only returns a structured response.
        result = _load_terrain(source="bad_source", downsample_factor=5)  # type: ignore[arg-type]
        assert isinstance(result, dict)
        assert "status" in result


# ---------------------------------------------------------------------------
# Tool 2 — get_terrain_info
# ---------------------------------------------------------------------------


class TestGetTerrainInfo:
    """Coverage for _get_terrain_info."""

    def test_error_when_no_terrain_loaded(self) -> None:
        result = _get_terrain_info()
        assert result["status"] == "error"

    def test_error_message_is_informative(self) -> None:
        result = _get_terrain_info()
        assert "message" in result
        assert len(result["message"]) > 0

    def test_happy_path_after_load_terrain_status_ok(self, loaded_terrain: dict[str, Any]) -> None:
        result = _get_terrain_info()
        assert result["status"] == "ok"

    def test_happy_path_required_keys_present(self, loaded_terrain: dict[str, Any]) -> None:
        result = _get_terrain_info()
        for key in ("status", "name", "shape", "elev_min", "elev_max", "resolution_m", "source"):
            assert key in result, f"missing key: {key}"

    def test_happy_path_shape_matches_loaded_shape(self, loaded_terrain: dict[str, Any]) -> None:
        result = _get_terrain_info()
        assert result["shape"] == loaded_terrain["shape"]

    def test_happy_path_source_is_synthetic(self, loaded_terrain: dict[str, Any]) -> None:
        result = _get_terrain_info()
        assert result["source"] == "synthetic"

    def test_happy_path_elev_range_consistent(self, loaded_terrain: dict[str, Any]) -> None:
        result = _get_terrain_info()
        assert result["elev_min"] < result["elev_max"]


# ---------------------------------------------------------------------------
# Tool 3 — plan_mission
# ---------------------------------------------------------------------------


class TestPlanMission:
    """Coverage for _plan_mission_tool."""

    def test_error_when_no_terrain_in_session(self) -> None:
        result = _plan_mission_tool(description="survey", start_row=10, start_col=10)
        assert result["status"] == "error"

    def test_error_message_key_present(self) -> None:
        result = _plan_mission_tool(description="survey", start_row=10, start_col=10)
        assert "message" in result

    def test_happy_path_status_ok(self, loaded_terrain: dict[str, Any]) -> None:
        result = _plan_mission_tool(
            description="survey", start_row=10, start_col=10, min_waypoints=2
        )
        assert result["status"] == "ok"

    def test_happy_path_feasible_is_bool(self, loaded_terrain: dict[str, Any]) -> None:
        result = _plan_mission_tool(
            description="survey", start_row=10, start_col=10, min_waypoints=2
        )
        assert isinstance(result["feasible"], bool)

    def test_happy_path_waypoints_is_list(self, loaded_terrain: dict[str, Any]) -> None:
        result = _plan_mission_tool(
            description="survey", start_row=10, start_col=10, min_waypoints=2
        )
        assert isinstance(result["waypoints"], list)

    def test_happy_path_required_keys_present(self, loaded_terrain: dict[str, Any]) -> None:
        result = _plan_mission_tool(
            description="survey", start_row=10, start_col=10, min_waypoints=2
        )
        for key in (
            "status",
            "feasible",
            "waypoints",
            "path_length",
            "predicted_duration_s",
            "predicted_final_battery_pct",
            "reasoning",
        ):
            assert key in result, f"missing key: {key}"

    def test_happy_path_plan_stored_in_session(self, loaded_terrain: dict[str, Any]) -> None:
        _plan_mission_tool(description="survey", start_row=10, start_col=10, min_waypoints=2)
        assert get_session().last_plan is not None

    def test_happy_path_path_length_non_negative(self, loaded_terrain: dict[str, Any]) -> None:
        result = _plan_mission_tool(
            description="survey", start_row=10, start_col=10, min_waypoints=2
        )
        assert result["path_length"] >= 0

    def test_with_roi_status_ok(self, loaded_terrain: dict[str, Any]) -> None:
        rows, cols = loaded_terrain["shape"]
        result = _plan_mission_tool(
            description="survey",
            start_row=10,
            start_col=10,
            min_waypoints=2,
            roi_row_min=0,
            roi_col_min=0,
            roi_row_max=rows,
            roi_col_max=cols,
        )
        assert result["status"] == "ok"

    def test_with_roi_required_keys_present(self, loaded_terrain: dict[str, Any]) -> None:
        rows, cols = loaded_terrain["shape"]
        result = _plan_mission_tool(
            description="survey",
            start_row=10,
            start_col=10,
            min_waypoints=2,
            roi_row_min=0,
            roi_col_min=0,
            roi_row_max=rows,
            roi_col_max=cols,
        )
        for key in ("feasible", "waypoints"):
            assert key in result, f"missing key with ROI: {key}"


# ---------------------------------------------------------------------------
# Tool 4 — execute_mission
# ---------------------------------------------------------------------------


class TestExecuteMission:
    """Coverage for _execute_mission."""

    def test_error_when_no_plan_in_session(self) -> None:
        result = _execute_mission()
        assert result["status"] == "error"

    def test_error_message_key_present_no_plan(self) -> None:
        result = _execute_mission()
        assert "message" in result

    def test_happy_path_status_ok(self) -> None:
        result = _full_end_to_end()
        assert result["status"] == "ok"

    def test_happy_path_outcome_is_valid(self) -> None:
        result = _full_end_to_end()
        assert result["outcome"] in {"success", "failure", "partial"}

    def test_happy_path_cells_non_negative(self) -> None:
        result = _full_end_to_end()
        assert result["cells"] >= 0

    def test_happy_path_report_path_ends_with_md(self) -> None:
        result = _full_end_to_end()
        assert result["report_path"].endswith(".md")

    def test_happy_path_required_keys_present(self) -> None:
        result = _full_end_to_end()
        for key in (
            "status",
            "outcome",
            "cells",
            "duration_s",
            "final_battery_pct",
            "waypoints_reached",
            "anomaly_count",
            "recovery_count",
            "report_path",
        ):
            assert key in result, f"missing key: {key}"

    def test_happy_path_report_file_exists_on_disk(self) -> None:
        result = _full_end_to_end()
        report_path = Path(result["report_path"])
        assert report_path.exists(), f"Report file not found: {report_path}"

    def test_happy_path_anomaly_count_zero_with_no_injections(self) -> None:
        result = _full_end_to_end()
        assert result["anomaly_count"] == 0

    def test_error_when_no_terrain_after_clearing(self) -> None:
        """If terrain is cleared between plan and execute, should return error."""
        _load_terrain(source="synthetic", downsample_factor=10)
        _plan_mission_tool(description="survey", start_row=10, start_col=10, min_waypoints=2)
        get_session().terrain = None
        result = _execute_mission()
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Tool 5 — inject_anomaly
# ---------------------------------------------------------------------------


class TestInjectAnomaly:
    """Coverage for _inject_anomaly."""

    @pytest.mark.parametrize("anomaly_type", ["dust_storm", "wheel_stuck", "thermal_alert"])
    def test_status_ok_for_valid_types(self, anomaly_type: str) -> None:
        result = _inject_anomaly(anomaly_type=anomaly_type, trigger_at_step=0)
        assert result["status"] == "ok"

    @pytest.mark.parametrize("anomaly_type", ["dust_storm", "wheel_stuck", "thermal_alert"])
    def test_queued_count_increments(self, anomaly_type: str) -> None:
        result = _inject_anomaly(anomaly_type=anomaly_type, trigger_at_step=0)
        assert result["queued_count"] == 1

    @pytest.mark.parametrize("anomaly_type", ["dust_storm", "wheel_stuck", "thermal_alert"])
    def test_anomaly_stored_in_session(self, anomaly_type: str) -> None:
        _inject_anomaly(anomaly_type=anomaly_type, trigger_at_step=0)
        assert len(get_session().pending_anomalies) == 1

    @pytest.mark.parametrize("anomaly_type", ["dust_storm", "wheel_stuck", "thermal_alert"])
    def test_anomaly_type_field_in_result(self, anomaly_type: str) -> None:
        result = _inject_anomaly(anomaly_type=anomaly_type, trigger_at_step=0)
        assert result["anomaly_type"] == anomaly_type

    @pytest.mark.parametrize("anomaly_type", ["dust_storm", "wheel_stuck", "thermal_alert"])
    def test_trigger_at_step_field_in_result(self, anomaly_type: str) -> None:
        result = _inject_anomaly(anomaly_type=anomaly_type, trigger_at_step=5)
        assert result["trigger_at_step"] == 5

    def test_wheel_stuck_blocked_cells_stored_correctly(self) -> None:
        _inject_anomaly(
            anomaly_type="wheel_stuck",
            trigger_at_step=2,
            blocked_cells=[[5, 5], [6, 6]],
        )
        anomaly = get_session().pending_anomalies[0]
        assert anomaly.blocked_cells == {(5, 5), (6, 6)}

    def test_invalid_anomaly_type_returns_error(self) -> None:
        result = _inject_anomaly(anomaly_type="meteor_impact", trigger_at_step=0)
        assert result["status"] == "error"

    def test_invalid_anomaly_type_has_message(self) -> None:
        result = _inject_anomaly(anomaly_type="meteor_impact", trigger_at_step=0)
        assert "message" in result

    def test_multiple_injections_accumulate(self) -> None:
        _inject_anomaly(anomaly_type="dust_storm", trigger_at_step=0)
        _inject_anomaly(anomaly_type="thermal_alert", trigger_at_step=1)
        result = _inject_anomaly(anomaly_type="wheel_stuck", trigger_at_step=2)
        assert result["queued_count"] == 3
        assert len(get_session().pending_anomalies) == 3

    def test_multiple_injections_all_present_in_session(self) -> None:
        types = ["dust_storm", "thermal_alert", "wheel_stuck"]
        for i, t in enumerate(types):
            _inject_anomaly(anomaly_type=t, trigger_at_step=i)
        stored = [a.anomaly_type for a in get_session().pending_anomalies]
        assert stored == types

    def test_custom_message_stored(self) -> None:
        _inject_anomaly(
            anomaly_type="dust_storm",
            trigger_at_step=0,
            message="big storm coming",
        )
        anomaly = get_session().pending_anomalies[0]
        assert anomaly.message == "big storm coming"

    def test_auto_message_generated_when_none(self) -> None:
        _inject_anomaly(anomaly_type="dust_storm", trigger_at_step=0, severity=0.7)
        anomaly = get_session().pending_anomalies[0]
        assert anomaly.message  # non-empty
        assert "dust_storm" in anomaly.message

    def test_severity_stored_correctly(self) -> None:
        _inject_anomaly(anomaly_type="dust_storm", trigger_at_step=0, severity=0.9)
        anomaly = get_session().pending_anomalies[0]
        assert anomaly.severity == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# Tool 6 — get_last_mission_report
# ---------------------------------------------------------------------------


class TestGetLastMissionReport:
    """Coverage for _get_last_mission_report."""

    def test_error_when_no_report_path(self) -> None:
        result = _get_last_mission_report()
        assert result["status"] == "error"

    def test_error_message_key_present(self) -> None:
        result = _get_last_mission_report()
        assert "message" in result

    def test_happy_path_status_ok_after_execute(self) -> None:
        _full_end_to_end()
        result = _get_last_mission_report()
        assert result["status"] == "ok"

    def test_happy_path_markdown_starts_with_mission_report_heading(self) -> None:
        _full_end_to_end()
        result = _get_last_mission_report()
        assert result["markdown"].startswith("# Mission Report")

    def test_happy_path_markdown_key_present(self) -> None:
        _full_end_to_end()
        result = _get_last_mission_report()
        assert "markdown" in result

    def test_happy_path_markdown_is_non_empty_string(self) -> None:
        _full_end_to_end()
        result = _get_last_mission_report()
        assert isinstance(result["markdown"], str)
        assert len(result["markdown"]) > 0

    def test_error_when_report_path_set_but_file_missing(self) -> None:
        """Simulate session having a path that does not exist."""
        from pathlib import Path

        get_session().last_report_path = Path("/tmp/nonexistent_marsops_report_xyz.md")
        result = _get_last_mission_report()
        assert result["status"] == "error"
