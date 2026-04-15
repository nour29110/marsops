"""MarsOps MCP server — exposes rover mission tools to Claude Desktop.

Run with::

    marsops-mcp          # via installed console script
    uv run marsops-mcp   # via uv without activation

The server speaks the MCP stdio protocol.  Six tools are registered:

* ``load_terrain``          — Load the Jezero Crater DEM into session.
* ``get_terrain_info``      — Query current terrain metadata.
* ``plan_mission``          — Plan an energy-feasible rover traverse.
* ``execute_mission``       — Execute the last plan (with anomaly injection).
* ``inject_anomaly``        — Queue an anomaly for the next execution.
* ``get_last_mission_report`` — Retrieve the last Markdown mission report.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from marsops.mcp_server.state import get_session
from marsops.planner.mission import MissionConstraints, MissionGoal
from marsops.planner.mission_planner_runtime import plan_mission as _plan_mission
from marsops.planner.recovery import recover_from_anomaly
from marsops.simulator.anomalies import Anomaly
from marsops.simulator.engine import execute_path_with_recovery
from marsops.simulator.rover import Rover
from marsops.telemetry.reporter import generate_mission_report
from marsops.terrain.loader import load_jezero_dem

logger = logging.getLogger(__name__)

# Resolve the project data directory relative to this file (src/marsops/mcp_server/server.py)
_DATA_DIR: Path = Path(__file__).resolve().parents[3] / "data"
_OUTPUT_DIR: Path = Path(__file__).resolve().parents[3] / "output"

mcp: FastMCP = FastMCP("marsops")

# ---------------------------------------------------------------------------
# Tool 1 — load_terrain
# ---------------------------------------------------------------------------


def _load_terrain(source: str = "synthetic", downsample_factor: int = 5) -> dict[str, Any]:
    """Load the Jezero Crater DEM into the session.

    Args:
        source: Which DEM to load. Use "synthetic" (default, fast, deterministic)
            or "real" (downloads ~9 MB USGS CTX GeoTIFF; requires internet).
        downsample_factor: Integer >= 1. Keep every Nth pixel to reduce grid size.
            Default 5 gives a ~100x100 grid from the 500x500 synthetic DEM.
            Use 1 for full resolution (slow for path planning).

    Returns:
        dict with keys:
            status (str): "ok" or "error".
            shape (list[int]): [rows, cols] of the loaded (downsampled) grid.
            elev_min (float): Minimum elevation in metres.
            elev_max (float): Maximum elevation in metres.
            resolution_m (float): Ground-sample distance in metres per pixel.
            source (str): Which source was loaded.
        On error: {"status": "error", "message": str}.
    """
    session = get_session()
    logger.info("load_terrain called: source=%s downsample_factor=%d", source, downsample_factor)
    if source not in ("synthetic", "real"):
        return {
            "status": "error",
            "message": f"Invalid source {source!r}. Must be 'synthetic' or 'real'.",
        }
    try:
        terrain = load_jezero_dem(_DATA_DIR, source=source)  # type: ignore[arg-type]
        if downsample_factor > 1:
            terrain = terrain.to_downsampled(downsample_factor)
        session.terrain = terrain
        session.terrain_source = source
        rows, cols = terrain.shape
        return {
            "status": "ok",
            "shape": [rows, cols],
            "elev_min": terrain.min_elevation,
            "elev_max": terrain.max_elevation,
            "resolution_m": terrain.metadata.resolution_m,
            "source": source,
        }
    except Exception as exc:
        logger.error("load_terrain failed: %s", exc)
        return {"status": "error", "message": str(exc)}


@mcp.tool()
def load_terrain(source: str = "synthetic", downsample_factor: int = 5) -> dict[str, Any]:
    """Load the Jezero Crater DEM into the session.

    Args:
        source: Which DEM to load. Use "synthetic" (default, fast, deterministic)
            or "real" (downloads ~9 MB USGS CTX GeoTIFF; requires internet).
        downsample_factor: Integer >= 1. Keep every Nth pixel to reduce grid size.
            Default 5 gives a ~100x100 grid from the 500x500 synthetic DEM.
            Use 1 for full resolution (slow for path planning).

    Returns:
        dict with keys:
            status (str): "ok" or "error".
            shape (list[int]): [rows, cols] of the loaded (downsampled) grid.
            elev_min (float): Minimum elevation in metres.
            elev_max (float): Maximum elevation in metres.
            resolution_m (float): Ground-sample distance in metres per pixel.
            source (str): Which source was loaded.
        On error: {"status": "error", "message": str}.
    """
    return _load_terrain(source=source, downsample_factor=downsample_factor)


# ---------------------------------------------------------------------------
# Tool 2 — get_terrain_info
# ---------------------------------------------------------------------------


def _get_terrain_info() -> dict[str, Any]:
    """Return metadata about the currently loaded terrain.

    Returns:
        dict with keys:
            status (str): "ok" or "error".
            name (str): Human-readable terrain dataset name.
            shape (list[int]): [rows, cols].
            elev_min (float): Minimum elevation in metres.
            elev_max (float): Maximum elevation in metres.
            resolution_m (float): Ground-sample distance in metres per pixel.
            source (str): Which source was loaded ("synthetic" or "real").
        On error: {"status": "error", "message": "No terrain loaded. Call load_terrain first."}.
    """
    session = get_session()
    logger.info("get_terrain_info called")
    if session.terrain is None:
        return {"status": "error", "message": "No terrain loaded. Call load_terrain first."}
    terrain = session.terrain
    rows, cols = terrain.shape
    return {
        "status": "ok",
        "name": terrain.metadata.name,
        "shape": [rows, cols],
        "elev_min": terrain.min_elevation,
        "elev_max": terrain.max_elevation,
        "resolution_m": terrain.metadata.resolution_m,
        "source": session.terrain_source or "unknown",
    }


@mcp.tool()
def get_terrain_info() -> dict[str, Any]:
    """Return metadata about the currently loaded terrain.

    Returns:
        dict with keys:
            status (str): "ok" or "error".
            name (str): Human-readable terrain dataset name.
            shape (list[int]): [rows, cols].
            elev_min (float): Minimum elevation in metres.
            elev_max (float): Maximum elevation in metres.
            resolution_m (float): Ground-sample distance in metres per pixel.
            source (str): Which source was loaded ("synthetic" or "real").
        On error: {"status": "error", "message": "No terrain loaded. Call load_terrain first."}.
    """
    return _get_terrain_info()


# ---------------------------------------------------------------------------
# Tool 3 — plan_mission
# ---------------------------------------------------------------------------


def _plan_mission_tool(
    description: str,
    start_row: int,
    start_col: int,
    min_waypoints: int = 2,
    must_return_to_start: bool = False,
    roi_row_min: int | None = None,
    roi_col_min: int | None = None,
    roi_row_max: int | None = None,
    roi_col_max: int | None = None,
) -> dict[str, Any]:
    """Plan an energy-feasible rover traverse mission.

    Requires terrain to be loaded first via load_terrain.

    Args:
        description: Free-text mission goal, e.g. "survey two flat sites in
            the northwest quadrant". Keywords "flat", "high", "low", "delta"
            influence waypoint selection.
        start_row: Starting grid row (0-based, must be within terrain bounds).
        start_col: Starting grid column (0-based, must be within terrain bounds).
        min_waypoints: Minimum number of distinct waypoints the plan must
            include (excluding start). Default 2.
        must_return_to_start: If True, the rover's route loops back to the
            start cell as the final waypoint. Default False.
        roi_row_min: Optional region-of-interest minimum row (inclusive).
            All four roi_* args must be provided together to activate ROI.
        roi_col_min: Optional region-of-interest minimum column (inclusive).
        roi_row_max: Optional region-of-interest maximum row (exclusive).
        roi_col_max: Optional region-of-interest maximum column (exclusive).

    Returns:
        dict with keys:
            status (str): "ok" or "error".
            feasible (bool): True if the plan satisfies all energy constraints.
            waypoints (list): List of [row, col] waypoints in visit order.
            path_length (int): Total number of cell moves in the planned path.
            predicted_duration_s (float): Estimated mission duration in seconds.
            predicted_final_battery_pct (float): Predicted battery % at end.
            reasoning (str): Natural-language explanation of planner decisions.
        On error: {"status": "error", "message": str}.
    """
    session = get_session()
    logger.info(
        "plan_mission called: start=(%d,%d) description=%r min_wps=%d",
        start_row,
        start_col,
        description,
        min_waypoints,
    )
    if session.terrain is None:
        return {"status": "error", "message": "No terrain loaded. Call load_terrain first."}
    terrain = session.terrain
    try:
        roi: tuple[int, int, int, int] | None = None
        if all(v is not None for v in (roi_row_min, roi_col_min, roi_row_max, roi_col_max)):
            roi = (
                int(roi_row_min),  # type: ignore[arg-type]
                int(roi_col_min),  # type: ignore[arg-type]
                int(roi_row_max),  # type: ignore[arg-type]
                int(roi_col_max),  # type: ignore[arg-type]
            )
        goal = MissionGoal(
            description=description,
            start=(start_row, start_col),
            region_of_interest=roi,
            min_waypoints=min_waypoints,
            constraints=MissionConstraints(must_return_to_start=must_return_to_start),
        )
        plan = _plan_mission(terrain, goal)
        session.last_plan = plan
        return {
            "status": "ok",
            "feasible": plan.feasible,
            "waypoints": [list(wp) for wp in plan.waypoints],
            "path_length": plan.predicted_distance_cells,
            "predicted_duration_s": plan.predicted_duration_s,
            "predicted_final_battery_pct": plan.predicted_final_battery_pct,
            "reasoning": plan.reasoning,
        }
    except Exception as exc:
        logger.error("plan_mission failed: %s", exc)
        return {"status": "error", "message": str(exc)}


@mcp.tool()
def plan_mission(
    description: str,
    start_row: int,
    start_col: int,
    min_waypoints: int = 2,
    must_return_to_start: bool = False,
    roi_row_min: int | None = None,
    roi_col_min: int | None = None,
    roi_row_max: int | None = None,
    roi_col_max: int | None = None,
) -> dict[str, Any]:
    """Plan an energy-feasible rover traverse mission.

    Requires terrain to be loaded first via load_terrain.

    Args:
        description: Free-text mission goal, e.g. "survey two flat sites in
            the northwest quadrant". Keywords "flat", "high", "low", "delta"
            influence waypoint selection.
        start_row: Starting grid row (0-based, must be within terrain bounds).
        start_col: Starting grid column (0-based, must be within terrain bounds).
        min_waypoints: Minimum number of distinct waypoints the plan must
            include (excluding start). Default 2.
        must_return_to_start: If True, the rover's route loops back to the
            start cell as the final waypoint. Default False.
        roi_row_min: Optional region-of-interest minimum row (inclusive).
            All four roi_* args must be provided together to activate ROI.
        roi_col_min: Optional region-of-interest minimum column (inclusive).
        roi_row_max: Optional region-of-interest maximum row (exclusive).
        roi_col_max: Optional region-of-interest maximum column (exclusive).

    Returns:
        dict with keys:
            status (str): "ok" or "error".
            feasible (bool): True if the plan satisfies all energy constraints.
            waypoints (list): List of [row, col] waypoints in visit order.
            path_length (int): Total number of cell moves in the planned path.
            predicted_duration_s (float): Estimated mission duration in seconds.
            predicted_final_battery_pct (float): Predicted battery % at end.
            reasoning (str): Natural-language explanation of planner decisions.
        On error: {"status": "error", "message": str}.
    """
    return _plan_mission_tool(
        description=description,
        start_row=start_row,
        start_col=start_col,
        min_waypoints=min_waypoints,
        must_return_to_start=must_return_to_start,
        roi_row_min=roi_row_min,
        roi_col_min=roi_col_min,
        roi_row_max=roi_row_max,
        roi_col_max=roi_col_max,
    )


# ---------------------------------------------------------------------------
# Tool 4 — execute_mission
# ---------------------------------------------------------------------------


def _execute_mission() -> dict[str, Any]:
    """Execute the most recently planned mission with optional anomaly injection.

    Requires a plan to exist in session (call plan_mission first). Constructs
    a fresh Rover at the plan's start position, replays any anomalies queued
    via inject_anomaly, and uses the heuristic recovery function to handle
    unexpected situations (dust storms, wheel sticking, thermal alerts).

    The mission report is written as Markdown to output/mcp_mission_<timestamp>.md
    relative to the project root.

    Returns:
        dict with keys:
            status (str): "ok" or "error".
            outcome (str): "success", "failure", or "partial".
            cells (int): Number of cell-to-cell moves executed.
            duration_s (float): Total mission duration in seconds.
            final_battery_pct (float): Battery percentage at mission end.
            waypoints_reached (int): Number of waypoints the rover visited.
            anomaly_count (int): Number of anomalies that were queued.
            recovery_count (int): Number of anomaly events in the log.
            report_path (str): Absolute path to the written Markdown report.
        On error: {"status": "error", "message": str}.
    """
    session = get_session()
    logger.info("execute_mission called")
    if session.last_plan is None:
        return {
            "status": "error",
            "message": "No mission plan in session. Call plan_mission first.",
        }
    if session.terrain is None:
        return {"status": "error", "message": "No terrain loaded. Call load_terrain first."}
    plan = session.last_plan
    terrain = session.terrain
    try:
        rover = Rover(terrain=terrain, start=plan.goal.start)
        session.rover = rover
        anomalies = list(session.pending_anomalies)
        anomaly_count = len(anomalies)
        waypoints_set = set(plan.waypoints)

        log = execute_path_with_recovery(
            rover=rover,
            path=plan.full_path,
            waypoints=waypoints_set,
            anomalies=anomalies,
            recovery_fn=recover_from_anomaly,
            terrain=terrain,
            original_goal=plan.goal,
        )
        session.last_log = log

        # Determine outcome
        event_types = {e.event_type for e in log.events}
        if "mission_failed" in event_types:
            outcome = "failure"
        elif "mission_complete" in event_types:
            outcome = "success"
        else:
            outcome = "partial"

        # Write report
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        report_path = _OUTPUT_DIR / f"mcp_mission_{timestamp}.md"
        terrain_name = terrain.metadata.name
        generate_mission_report(
            log, terrain_name, report_path, planned_waypoints=len(plan.waypoints)
        )
        session.last_report_path = report_path

        recovery_count = sum(1 for e in log.events if e.event_type == "recovery_replan")

        return {
            "status": "ok",
            "outcome": outcome,
            "cells": log.distance_cells(),
            "duration_s": log.duration_s(),
            "final_battery_pct": log.final_battery(),
            "waypoints_reached": log.waypoints_reached(),
            "anomaly_count": anomaly_count,
            "recovery_count": recovery_count,
            "report_path": str(report_path.resolve()),
        }
    except Exception as exc:
        logger.error("execute_mission failed: %s", exc)
        return {"status": "error", "message": str(exc)}


@mcp.tool()
def execute_mission() -> dict[str, Any]:
    """Execute the most recently planned mission with optional anomaly injection.

    Requires a plan to exist in session (call plan_mission first). Constructs
    a fresh Rover at the plan's start position, replays any anomalies queued
    via inject_anomaly, and uses the heuristic recovery function to handle
    unexpected situations (dust storms, wheel sticking, thermal alerts).

    The mission report is written as Markdown to output/mcp_mission_<timestamp>.md
    relative to the project root.

    Returns:
        dict with keys:
            status (str): "ok" or "error".
            outcome (str): "success", "failure", or "partial".
            cells (int): Number of cell-to-cell moves executed.
            duration_s (float): Total mission duration in seconds.
            final_battery_pct (float): Battery percentage at mission end.
            waypoints_reached (int): Number of waypoints the rover visited.
            anomaly_count (int): Number of anomalies that were queued.
            recovery_count (int): Number of anomaly events in the log.
            report_path (str): Absolute path to the written Markdown report.
        On error: {"status": "error", "message": str}.
    """
    return _execute_mission()


# ---------------------------------------------------------------------------
# Tool 5 — inject_anomaly
# ---------------------------------------------------------------------------


def _inject_anomaly(
    anomaly_type: str,
    trigger_at_step: int,
    severity: float = 0.5,
    blocked_cells: list[list[int]] | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    """Queue an anomaly to be injected during the next execute_mission call.

    Anomalies are consumed (cleared) after each execute_mission call. You can
    inject multiple anomalies before executing; they fire in step order.

    Args:
        anomaly_type: Category of anomaly. Must be one of:
            "dust_storm"   — drains battery and forces an idle wait period.
            "wheel_stuck"  — marks cells as impassable, triggering rerouting.
            "thermal_alert" — forces a long idle wait (rover must cool down).
        trigger_at_step: Zero-indexed path step at which this anomaly fires.
            Step 0 fires immediately before the first move.
        severity: Float in [0.0, 1.0]. Higher values mean stronger effects.
            Default 0.5 (moderate).
        blocked_cells: For "wheel_stuck" anomalies only. List of [row, col]
            pairs that become impassable. Ignored for other anomaly types.
        message: Optional human-readable description. Auto-generated if omitted.

    Returns:
        dict with keys:
            status (str): "ok" or "error".
            queued_count (int): Total anomalies now queued for next execution.
            anomaly_type (str): The type that was queued.
            trigger_at_step (int): The step at which it will fire.
        On error: {"status": "error", "message": str}.
    """
    session = get_session()
    logger.info(
        "inject_anomaly called: type=%s step=%d severity=%.2f",
        anomaly_type,
        trigger_at_step,
        severity,
    )
    valid_types = {"dust_storm", "wheel_stuck", "thermal_alert"}
    if anomaly_type not in valid_types:
        return {
            "status": "error",
            "message": (
                f"Invalid anomaly_type {anomaly_type!r}. Must be one of: {sorted(valid_types)}"
            ),
        }
    try:
        auto_msg = message or f"{anomaly_type} anomaly (severity={severity:.2f})"
        cells: set[tuple[int, int]] | None = None
        if blocked_cells:
            cells = {(int(rc[0]), int(rc[1])) for rc in blocked_cells}
        anomaly = Anomaly(
            trigger_at_step=trigger_at_step,
            anomaly_type=anomaly_type,  # type: ignore[arg-type]
            severity=severity,
            message=auto_msg,
            blocked_cells=cells,
        )
        session.pending_anomalies.append(anomaly)
        return {
            "status": "ok",
            "queued_count": len(session.pending_anomalies),
            "anomaly_type": anomaly_type,
            "trigger_at_step": trigger_at_step,
        }
    except Exception as exc:
        logger.error("inject_anomaly failed: %s", exc)
        return {"status": "error", "message": str(exc)}


@mcp.tool()
def inject_anomaly(
    anomaly_type: str,
    trigger_at_step: int,
    severity: float = 0.5,
    blocked_cells: list[list[int]] | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    """Queue an anomaly to be injected during the next execute_mission call.

    Anomalies are consumed (cleared) after each execute_mission call. You can
    inject multiple anomalies before executing; they fire in step order.

    Args:
        anomaly_type: Category of anomaly. Must be one of:
            "dust_storm"   — drains battery and forces an idle wait period.
            "wheel_stuck"  — marks cells as impassable, triggering rerouting.
            "thermal_alert" — forces a long idle wait (rover must cool down).
        trigger_at_step: Zero-indexed path step at which this anomaly fires.
            Step 0 fires immediately before the first move.
        severity: Float in [0.0, 1.0]. Higher values mean stronger effects.
            Default 0.5 (moderate).
        blocked_cells: For "wheel_stuck" anomalies only. List of [row, col]
            pairs that become impassable. Ignored for other anomaly types.
        message: Optional human-readable description. Auto-generated if omitted.

    Returns:
        dict with keys:
            status (str): "ok" or "error".
            queued_count (int): Total anomalies now queued for next execution.
            anomaly_type (str): The type that was queued.
            trigger_at_step (int): The step at which it will fire.
        On error: {"status": "error", "message": str}.
    """
    return _inject_anomaly(
        anomaly_type=anomaly_type,
        trigger_at_step=trigger_at_step,
        severity=severity,
        blocked_cells=blocked_cells,
        message=message,
    )


# ---------------------------------------------------------------------------
# Tool 6 — get_last_mission_report
# ---------------------------------------------------------------------------

_MAX_REPORT_BYTES: int = 50 * 1024  # 50 KB


def _get_last_mission_report() -> dict[str, Any]:
    """Retrieve the full Markdown content of the last mission report.

    Reads the report file written by the most recent execute_mission call.
    Response is capped at 50 KB; longer reports are truncated with a notice.

    Returns:
        dict with keys:
            status (str): "ok" or "error".
            markdown (str): Full (or truncated) Markdown report content.
        On error: {"status": "error", "message": "No report available."}.
    """
    session = get_session()
    logger.info("get_last_mission_report called")
    if session.last_report_path is None or not session.last_report_path.exists():
        return {
            "status": "error",
            "message": "No mission report available. Run execute_mission first.",
        }
    try:
        content = session.last_report_path.read_text(encoding="utf-8")
        if len(content.encode("utf-8")) > _MAX_REPORT_BYTES:
            truncated = content.encode("utf-8")[:_MAX_REPORT_BYTES].decode("utf-8", errors="ignore")
            content = truncated + "\n\n[Report truncated at 50 KB]"
        return {"status": "ok", "markdown": content}
    except Exception as exc:
        logger.error("get_last_mission_report failed: %s", exc)
        return {"status": "error", "message": str(exc)}


@mcp.tool()
def get_last_mission_report() -> dict[str, Any]:
    """Retrieve the full Markdown content of the last mission report.

    Reads the report file written by the most recent execute_mission call.
    Response is capped at 50 KB; longer reports are truncated with a notice.

    Returns:
        dict with keys:
            status (str): "ok" or "error".
            markdown (str): Full (or truncated) Markdown report content.
        On error: {"status": "error", "message": "No report available."}.
    """
    return _get_last_mission_report()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the MarsOps MCP stdio server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    mcp.run()


if __name__ == "__main__":
    main()
