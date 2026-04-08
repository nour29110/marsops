"""Mission execution engine.

Walks a :class:`~marsops.simulator.rover.Rover` along a pre-planned path,
emitting :class:`~marsops.telemetry.events.TelemetryEvent` records and
assembling them into a :class:`~marsops.telemetry.events.MissionLog`.

Two entry points are provided:

* :func:`execute_path` -- original stepper with no anomaly handling.
* :func:`execute_path_with_recovery` -- extended stepper that injects
  mid-mission anomalies, applies their effects, and invokes an optional
  recovery function when the situation changes materially.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from marsops.planner.astar import NoPathFoundError, astar
from marsops.planner.mission import MissionGoal
from marsops.planner.recovery import RecoveryStrategy
from marsops.simulator.anomalies import Anomaly, apply_anomaly
from marsops.simulator.rover import Rover, RoverConfig, RoverFailure
from marsops.telemetry.events import MissionLog, TelemetryEvent
from marsops.terrain.loader import Terrain

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


# ---------------------------------------------------------------------------
# execute_path_with_recovery
# ---------------------------------------------------------------------------


def execute_path_with_recovery(
    rover: Rover,
    path: list[tuple[int, int]],
    waypoints: set[tuple[int, int]] | None = None,
    anomalies: list[Anomaly] | None = None,
    recovery_fn: Callable[..., RecoveryStrategy] | None = None,
    terrain: Terrain | None = None,
    original_goal: MissionGoal | None = None,
    rover_config: RoverConfig | None = None,
    max_recoveries: int = 5,
) -> MissionLog:
    """Execute a planned path with optional mid-mission anomaly injection and recovery.

    Extends :func:`execute_path` with the ability to inject anomalies at
    specific path steps, apply their effects to the rover state, and
    optionally call a *recovery_fn* when the situation changes materially
    (blocked cells discovered, or battery drops below the low-battery
    threshold).

    Recovery outcomes:

    * ``"replan_around"`` / ``"reduce_ambition"`` — the engine switches to the
      new path from the recovery plan, emits a ``"recovery_replan"`` event, and
      continues execution.
    * ``"abort_to_start"`` — the engine attempts to navigate the rover back to
      ``original_goal.start`` via A*, then emits ``"mission_failed"`` with the
      abort reason and returns.
    * ``"continue"`` — carry on along the current path unchanged.

    The original :func:`execute_path` behaviour is fully preserved when
    *anomalies* is empty (or ``None``) and *recovery_fn* is ``None``.

    Args:
        rover: Initialised :class:`~marsops.simulator.rover.Rover` instance.
            Its initial position should match ``path[0]``.
        path: Ordered list of ``(row, col)`` coordinates to traverse.
        waypoints: Optional set of ``(row, col)`` coordinates that trigger a
            ``"waypoint_reached"`` event when visited.
        anomalies: Optional list of :class:`~marsops.simulator.anomalies.Anomaly`
            objects.  Each fires exactly once at its ``trigger_at_step`` index
            (0-indexed over the whole walk; persists across replanning).
        recovery_fn: Optional callable matching the signature of
            :func:`~marsops.planner.recovery.recover_from_anomaly`.  Called
            when an anomaly changes the situation materially; receives
            ``(terrain, rover, original_goal, remaining_waypoints,
            blocked_cells, rover_config)`` and must return a
            :class:`~marsops.planner.recovery.RecoveryStrategy`.
        terrain: Terrain grid forwarded to *recovery_fn* and used for abort
            path planning.  Required when *recovery_fn* is provided.
        original_goal: Original :class:`~marsops.planner.mission.MissionGoal`;
            used for recovery context and abort-to-start navigation.
        rover_config: Optional rover configuration forwarded to *recovery_fn*.
        max_recoveries: Maximum number of recovery attempts before the engine
            forces an ``"abort_to_start"`` outcome.  Prevents infinite
            replanning loops.  Defaults to 5.

    Returns:
        A :class:`~marsops.telemetry.events.MissionLog` containing all events
        emitted during the run (complete or partial).
    """
    if waypoints is None:
        waypoints = set()
    if anomalies is None:
        anomalies = []

    # Index anomalies by step for O(1) lookup; keep original list index so
    # each anomaly fires at most once even across replanning.
    anomaly_map: dict[int, list[tuple[int, Anomaly]]] = {}
    for anomaly_idx, anomaly in enumerate(anomalies):
        anomaly_map.setdefault(anomaly.trigger_at_step, []).append((anomaly_idx, anomaly))

    # Tracks which anomalies have already fired (by original list index).
    fired_anomaly_ids: set[int] = set()
    # Counts how many recovery calls have been made this mission.
    recovery_count = 0

    # Derive ordered remaining waypoints from path (visit order in path)
    _seen_wps: set[tuple[int, int]] = set()
    remaining_wps: list[tuple[int, int]] = []
    for cell in path[1:]:
        if cell in waypoints and cell not in _seen_wps:
            _seen_wps.add(cell)
            remaining_wps.append(cell)

    # Accumulated blocked cells across all anomaly effects
    all_blocked_cells: set[tuple[int, int]] = set()

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
    events.append(_make_event("mission_start", f"Mission started at {rover.position}"))

    if len(path) < 2:
        events.append(
            _make_event(
                "mission_complete",
                f"Mission complete at {rover.position} (trivial path)",
            )
        )
        return MissionLog(events=events)

    # -- walk path with anomaly injection ------------------------------------
    current_tail: list[tuple[int, int]] = list(path[1:])
    step_idx: int = 0

    while current_tail:
        next_cell = current_tail[0]
        replanned = False

        # -- check anomalies that fire at this step -------------------------
        for anomaly_idx, anomaly in anomaly_map.get(step_idx, []):
            # Each anomaly fires at most once, even across path replanning.
            if anomaly_idx in fired_anomaly_ids:
                continue
            fired_anomaly_ids.add(anomaly_idx)

            effect = apply_anomaly(rover, anomaly)
            events.append(_make_event("anomaly", anomaly.message))
            all_blocked_cells |= effect.new_blocked_cells

            # Determine whether recovery is warranted
            needs_recovery = bool(effect.new_blocked_cells) or (
                effect.battery_drain_pct > 0.0
                and rover.battery_pct < rover.config.low_battery_threshold_pct
            )

            if recovery_fn is not None and terrain is not None and needs_recovery:
                if recovery_count >= max_recoveries:
                    logger.warning(
                        "Max recoveries (%d) reached at step %d — forcing abort_to_start",
                        max_recoveries,
                        step_idx,
                    )
                    strategy = RecoveryStrategy(
                        strategy_type="abort_to_start",
                        new_plan=None,
                        reasoning=(
                            f"Max recoveries ({max_recoveries}) exceeded at step {step_idx}"
                        ),
                    )
                else:
                    recovery_count += 1
                    try:
                        strategy = recovery_fn(
                            terrain,
                            rover,
                            original_goal,
                            list(remaining_wps),
                            all_blocked_cells,
                            rover_config,
                        )
                    except Exception as exc:
                        logger.error("recovery_fn raised unexpectedly: %s", exc)
                        strategy = RecoveryStrategy(
                            strategy_type="continue",
                            new_plan=None,
                            reasoning=f"recovery_fn raised: {exc}",
                        )

                logger.info(
                    "Recovery strategy: %s at step %d pos=%s",
                    strategy.strategy_type,
                    step_idx,
                    rover.position,
                )

                if (
                    strategy.strategy_type in ("replan_around", "reduce_ambition")
                    and strategy.new_plan is not None
                ):
                    events.append(
                        _make_event(
                            "recovery_replan",
                            f"Recovery ({strategy.strategy_type}): {strategy.reasoning}",
                        )
                    )
                    new_path = strategy.new_plan.full_path
                    current_tail = list(new_path[1:]) if len(new_path) > 1 else []
                    # Update waypoints set and remaining list from new plan
                    waypoints = set(strategy.new_plan.waypoints)
                    _seen_r: set[tuple[int, int]] = set()
                    remaining_wps = []
                    for cell in current_tail:
                        if cell in waypoints and cell not in _seen_r:
                            _seen_r.add(cell)
                            remaining_wps.append(cell)
                    replanned = True
                    break  # exit anomaly loop; while will re-read current_tail[0]

                elif strategy.strategy_type == "abort_to_start":
                    abort_reason = strategy.reasoning
                    logger.warning("Engine: aborting mission to start — %s", abort_reason)
                    # Attempt abort drive if we know the start location
                    if original_goal is not None and terrain is not None:
                        _drive_abort_to_start(
                            rover=rover,
                            goal_start=original_goal.start,
                            terrain=terrain,
                            events=events,
                            make_event=_make_event,
                        )
                    events.append(
                        _make_event(
                            "mission_failed",
                            f"Mission aborted: {abort_reason}",
                        )
                    )
                    return MissionLog(events=events)
                # strategy_type == "continue": fall through to step execution

        if replanned:
            # Path has changed; restart while loop to get new next_cell
            continue

        # -- execute the step ------------------------------------------------
        try:
            step_event = rover.step_to(next_cell)
        except RoverFailure as exc:
            logger.warning("RoverFailure during recovery mission: %s", exc)
            events.append(_make_event("mission_failed", f"Mission failed: {exc}"))
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
            events.append(_make_event("waypoint_reached", f"Waypoint reached: {rover.position}"))
            if rover.position in remaining_wps:
                remaining_wps.remove(rover.position)

        current_tail = current_tail[1:]
        step_idx += 1

    # -- mission_complete ----------------------------------------------------
    events.append(_make_event("mission_complete", f"Mission complete at {rover.position}"))
    logger.info(
        "Mission complete (with recovery): %d events, %.1f s, %.1f%% battery remaining",
        len(events),
        rover.clock_s,
        rover.battery_pct,
    )
    return MissionLog(events=events)


def _drive_abort_to_start(
    rover: Rover,
    goal_start: tuple[int, int],
    terrain: Terrain,
    events: list[TelemetryEvent],
    make_event: Callable[..., TelemetryEvent],
) -> None:
    """Attempt to drive the rover back to *goal_start* via A* and emit step events.

    A best-effort helper: if A* cannot find a path (e.g. blocked terrain) or
    the rover exhausts its battery during the abort drive, the function returns
    silently without raising.  The caller always appends ``"mission_failed"``
    afterwards regardless of whether the abort drive succeeded.

    Args:
        rover: Live rover instance (state mutated in-place).
        goal_start: Target ``(row, col)`` cell to return to.
        terrain: Terrain grid for A* planning.
        events: Event list to append step events to.
        make_event: Factory callable ``(event_type, message) -> TelemetryEvent``.
    """
    if rover.position == goal_start:
        return  # already at start

    try:
        abort_path = astar(terrain, rover.position, goal_start)
    except (NoPathFoundError, ValueError) as exc:
        logger.warning("Abort path A* failed from %s to %s: %s", rover.position, goal_start, exc)
        return

    logger.info(
        "Executing abort drive: %d cells from %s to %s",
        len(abort_path),
        rover.position,
        goal_start,
    )
    for cell in abort_path[1:]:
        try:
            step_event = rover.step_to(cell)
            events.append(step_event)
        except (RoverFailure, ValueError) as exc:
            logger.warning("Abort drive interrupted at %s: %s", cell, exc)
            return
