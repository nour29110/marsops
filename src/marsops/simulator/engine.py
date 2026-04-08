"""Mission execution engine.

Walks a :class:`~marsops.simulator.rover.Rover` along a pre-planned path,
emitting :class:`~marsops.telemetry.events.TelemetryEvent` records and
assembling them into a :class:`~marsops.telemetry.events.MissionLog`.
"""

from __future__ import annotations

import logging

from marsops.simulator.rover import Rover, RoverFailure
from marsops.telemetry.events import MissionLog, TelemetryEvent

logger = logging.getLogger(__name__)


def execute_path(
    rover: Rover,
    path: list[tuple[int, int]],
    waypoints: set[tuple[int, int]] | None = None,
) -> MissionLog:
    """Execute a planned path on the rover and return the mission telemetry log.

    Walks the rover cell-by-cell along *path*, emitting one event per move.
    Special events are inserted for:

    * ``"mission_start"`` — emitted before the first move.
    * ``"step"`` — emitted by the rover for each cell transition.
    * ``"waypoint_reached"`` — emitted immediately after a ``"step"`` event
      when the new position is a member of *waypoints*.
    * ``"low_battery"`` — emitted the **first** time the battery percentage
      drops below the rover's configured threshold.
    * ``"mission_complete"`` — emitted when the rover successfully reaches the
      last cell of the path.
    * ``"mission_failed"`` — emitted when :exc:`~marsops.simulator.rover.RoverFailure`
      is raised; the partial log is returned without re-raising.

    This function never raises; all failures are captured and recorded.

    Args:
        rover: Initialised :class:`~marsops.simulator.rover.Rover` instance.
            Its initial position should match ``path[0]``.
        path: Ordered list of ``(row, col)`` coordinates to traverse.
        waypoints: Optional set of ``(row, col)`` coordinates that trigger
            a ``"waypoint_reached"`` event when visited.

    Returns:
        A :class:`~marsops.telemetry.events.MissionLog` containing all events
        emitted during the run (complete or partial).
    """
    if waypoints is None:
        waypoints = set()

    events: list[TelemetryEvent] = []
    low_battery_emitted = False

    def _make_event(event_type: str, message: str) -> TelemetryEvent:
        row, col = rover.position
        return TelemetryEvent(
            timestamp_s=rover.clock_s,
            event_type=event_type,  # type: ignore[arg-type]
            position=rover.position,
            battery_pct=rover.battery_pct,
            elevation_m=rover.terrain.elevation_at(row, col),
            heading_deg=rover.heading_deg,
            message=message,
        )

    # -- mission_start -------------------------------------------------------
    events.append(
        _make_event(
            "mission_start",
            f"Mission started at {rover.position}",
        )
    )

    if len(path) < 2:
        # Single-cell path: already at goal.
        events.append(
            _make_event(
                "mission_complete",
                f"Mission complete at {rover.position} (trivial path)",
            )
        )
        return MissionLog(events=events)

    # -- walk path -----------------------------------------------------------
    for next_cell in path[1:]:
        try:
            step_event = rover.step_to(next_cell)
        except RoverFailure as exc:
            logger.warning("RoverFailure during mission: %s", exc)
            events.append(
                _make_event(
                    "mission_failed",
                    f"Mission failed: {exc}",
                )
            )
            return MissionLog(events=events)

        events.append(step_event)

        # low_battery — first crossing only
        if not low_battery_emitted and rover.battery_pct < rover.config.low_battery_threshold_pct:
            low_battery_emitted = True
            events.append(
                _make_event(
                    "low_battery",
                    f"Low battery: {rover.battery_pct:.1f}% at {rover.position}",
                )
            )

        # waypoint_reached
        if rover.position in waypoints:
            events.append(
                _make_event(
                    "waypoint_reached",
                    f"Waypoint reached: {rover.position}",
                )
            )

    # -- mission_complete ----------------------------------------------------
    events.append(
        _make_event(
            "mission_complete",
            f"Mission complete at {rover.position}",
        )
    )

    logger.info(
        "Mission complete: %d events, %.1f s, %.1f%% battery remaining",
        len(events),
        rover.clock_s,
        rover.battery_pct,
    )
    return MissionLog(events=events)
