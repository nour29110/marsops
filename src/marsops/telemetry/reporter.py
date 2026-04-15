"""Mission report generator in the JPL sol-report style.

Consumes a :class:`~marsops.telemetry.events.MissionLog` and writes a
structured Markdown mission debrief to a file.  Every figure in the report
is derived from the telemetry event list,no values are fabricated.
"""

from __future__ import annotations

import logging
from pathlib import Path

from marsops.telemetry.events import MissionLog, TelemetryEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_NOTABLE_TYPES = {
    "mission_start",
    "waypoint_reached",
    "low_battery",
    "anomaly",
    "recovery_replan",
    "mission_complete",
    "mission_failed",
}


def _outcome(log: MissionLog) -> str:
    """Derive mission outcome string from the event log.

    Args:
        log: The mission log to inspect.

    Returns:
        One of ``"success"``, ``"failure"``, or ``"partial"``.
    """
    types = {e.event_type for e in log.events}
    if "mission_failed" in types:
        return "failure"
    if "mission_complete" in types:
        return "success"
    return "partial"


def _recommendation(log: MissionLog) -> str:
    """Build the recommendation line based on final battery and outcome.

    Args:
        log: The mission log to inspect.

    Returns:
        A one-line markdown string with a status indicator.
    """
    outcome = _outcome(log)
    battery = log.final_battery()

    if outcome == "failure" or battery < 20.0:
        return "ABORT,mission failed or battery critically low; suspend operations."
    if battery < 40.0 or outcome == "partial":
        return (
            "RETURN TO BASE,battery below 40% or mission only partially completed;"
            " navigate to nearest charging station."
        )
    return "CONTINUE,mission succeeded with adequate battery reserve; proceed to next objective."


def _build_report(log: MissionLog, terrain_name: str, planned_waypoints: int) -> str:
    """Assemble the full sol-report markdown string.

    Args:
        log: Populated mission log.
        terrain_name: Human-readable name of the terrain dataset.
        planned_waypoints: Number of waypoints in the executed plan, used as
            the denominator in the waypoints-reached metric.

    Returns:
        Complete report as a markdown string.
    """
    outcome = _outcome(log)
    start_event: TelemetryEvent | None = next(
        (e for e in log.events if e.event_type == "mission_start"), None
    )
    end_event: TelemetryEvent | None = log.events[-1] if log.events else None

    start_battery = start_event.battery_pct if start_event else 0.0
    end_battery = log.final_battery()
    duration = log.duration_s()
    distance = log.distance_cells()
    wps_reached = log.waypoints_reached()
    wps_total = max(planned_waypoints, wps_reached)

    start_pos = start_event.position if start_event else (0, 0)
    end_pos = end_event.position if end_event else (0, 0)

    recovery_count = sum(1 for e in log.events if e.event_type == "recovery_replan")

    # ,Mission Summary -----------------------------------------------------
    summary = (
        f"The rover executed a traverse mission on terrain **{terrain_name}**, "
        f"starting at grid position {start_pos} and finishing at {end_pos}. "
        f"Mission outcome: **{outcome}**. "
        f"The rover covered {distance} cell(s) in {duration:.2f} s, "
        f"consuming {start_battery - end_battery:.2f} percentage points of battery capacity. "
    )
    if outcome == "failure":
        summary += "A mission-failed event was recorded; the rover halted before reaching the goal."
    elif outcome == "success" and recovery_count > 0:
        summary += (
            f"All objectives were completed after **{recovery_count} recovery action(s)**; "
            "the rover adapted its route in response to an anomaly."
        )
    elif outcome == "success":
        summary += "All objectives were completed and the rover reached the designated goal."
    else:
        summary += "The mission ended without a completion event; log may be truncated."

    # ,Key Metrics table ---------------------------------------------------
    metrics = (
        "| Metric | Value |\n"
        "|--------|-------|\n"
        f"| Distance | {distance} cells |\n"
        f"| Duration | {duration:.2f} s |\n"
        f"| Start battery | {start_battery:.2f} % |\n"
        f"| End battery | {end_battery:.2f} % |\n"
        f"| Waypoints reached | {wps_reached} / {wps_total} |\n"
        f"| Recovery actions | {recovery_count} |\n"
    )

    # ,Timeline of Notable Events -----------------------------------------
    timeline_rows: list[str] = []
    low_battery_seen = False
    for event in log.events:
        et = event.event_type
        if et == "low_battery":
            if low_battery_seen:
                continue
            low_battery_seen = True
        if et not in _NOTABLE_TYPES:
            continue
        note = event.message.split("(")[0].strip() if "(" in event.message else event.message
        row = (
            f"| {event.timestamp_s:.2f} "
            f"| {et} "
            f"| {event.position} "
            f"| {event.battery_pct:.2f} "
            f"| {note} |"
        )
        timeline_rows.append(row)

    timeline_header = (
        "| Time (s) | Event | Position | Battery (%) | Note |\n"
        "|----------|-------|----------|-------------|------|\n"
    )
    timeline = timeline_header + "\n".join(timeline_rows)

    # ,Anomalies -----------------------------------------------------------
    anomaly_events = [
        e
        for e in log.events
        if e.event_type in {"anomaly", "recovery_replan", "low_battery", "mission_failed"}
    ]
    if anomaly_events:
        anomaly_lines = [
            f"- **{e.event_type}** at t={e.timestamp_s:.2f} s, "
            f"position={e.position}, battery={e.battery_pct:.2f} %: {e.message}"
            for e in anomaly_events
        ]
        anomalies = "\n".join(anomaly_lines)
    else:
        anomalies = "No anomalies detected."

    # ,Recommendation -------------------------------------------------------
    recommendation = _recommendation(log)

    # ,Assemble -----------------------------------------------------------
    report = (
        "# Mission Report\n\n"
        "## Mission Summary\n\n"
        f"{summary}\n\n"
        "## Key Metrics\n\n"
        f"{metrics}\n"
        "## Timeline of Notable Events\n\n"
        f"{timeline}\n\n"
        "## Anomalies\n\n"
        f"{anomalies}\n\n"
        "## Recommendation\n\n"
        f"{recommendation}\n"
    )
    return report


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_mission_report(
    log: MissionLog,
    terrain_name: str,
    output_path: Path,
    planned_waypoints: int = 0,
) -> Path:
    """Generate a sol-report-style Markdown mission debrief from a MissionLog.

    Every figure in the report is derived directly from the telemetry event
    list in *log*.  The file is written to *output_path* and the path is
    returned.

    Args:
        log: Populated :class:`~marsops.telemetry.events.MissionLog` from a
            completed (or partial/failed) mission run.
        terrain_name: Human-readable name for the terrain, inserted into the
            mission summary paragraph.
        output_path: Destination ``.md`` file path.  Parent directories are
            created automatically.
        planned_waypoints: Number of waypoints in the executed plan.  Used as
            the denominator in the waypoints-reached metric.  Defaults to 0,
            which causes the denominator to equal the reached count.

    Returns:
        The resolved *output_path* after writing.
    """
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    report = _build_report(log, terrain_name, planned_waypoints)
    output_path.write_text(report, encoding="utf-8")

    logger.info(
        "Mission report written to %s (%d events, outcome=%s)",
        output_path,
        len(log.events),
        _outcome(log),
    )
    return output_path
