"""Dry-run mission simulation for pre-flight plan validation.

Provides a lightweight, non-event-emitting simulation that predicts mission
outcomes (duration, final battery, distance) before committing to a live run.
The planner calls these functions iteratively during the refinement loop.
"""

from __future__ import annotations

import logging

from marsops.planner.astar import NoPathFoundError, astar
from marsops.planner.mission import MissionConstraints
from marsops.simulator.rover import Rover, RoverConfig, RoverFailure
from marsops.terrain.loader import Terrain

logger = logging.getLogger(__name__)


def dry_run_mission(
    terrain: Terrain,
    start: tuple[int, int],
    waypoints: list[tuple[int, int]],
    rover_config: RoverConfig | None = None,
) -> tuple[list[tuple[int, int]], float, float, int]:
    """Predict mission outcome by dry-running A* + simulation without events.

    Plans A* segments from start through each waypoint in order, concatenates
    them into a single path, then simulates a private :class:`~marsops.simulator.rover.Rover`
    walking that path.  No telemetry events are emitted; this is a pure
    prediction function that may be called many times cheaply during planning.

    If any A* segment between consecutive points fails (``NoPathFoundError``
    or ``ValueError``) or the rover exhausts its battery (``RoverFailure``),
    the function returns the partial results collected up to the failure point
    with ``predicted_final_battery_pct < 0`` signalling the failure.

    Args:
        terrain: Elevation grid to plan over.
        start: Starting cell as ``(row, col)``.
        waypoints: Ordered list of target cells to visit after *start*.
            May be empty, in which case a trivial single-cell path is returned.
        rover_config: Rover configuration; defaults to
            :class:`~marsops.simulator.rover.RoverConfig` defaults.

    Returns:
        A 4-tuple ``(full_path, predicted_duration_s,
        predicted_final_battery_pct, distance_cells)`` where:

        * ``full_path`` is the concatenated cell sequence.
        * ``predicted_duration_s`` is the simulated elapsed time.
        * ``predicted_final_battery_pct`` is the battery percentage remaining.
          **Negative values indicate failure** (A* or battery exhaustion).
        * ``distance_cells`` is the number of cell-to-cell moves completed.
    """
    config = rover_config if rover_config is not None else RoverConfig()

    # Trivial: no waypoints → rover stays at start.
    # Battery is returned as 100.0 because a freshly initialised Rover always
    # starts at full charge (battery_capacity_wh = 100 %).  This function
    # always constructs a new Rover from scratch, so this assumption holds.
    if not waypoints:
        return ([start], 0.0, 100.0, 0)

    # -- Plan A* segments -------------------------------------------------------
    full_path: list[tuple[int, int]] = [start]
    stops = [start, *waypoints]

    for i in range(len(stops) - 1):
        seg_start = stops[i]
        seg_goal = stops[i + 1]
        if seg_start == seg_goal:
            continue
        try:
            segment = astar(terrain, seg_start, seg_goal)
        except (NoPathFoundError, ValueError) as exc:
            logger.debug("A* failed from %s to %s: %s", seg_start, seg_goal, exc)
            # Return partial path with failure signal
            return (full_path, 0.0, -1.0, 0)

        # Skip first cell of each subsequent segment (already in full_path)
        full_path.extend(segment[1:])

    # -- Simulate rover walk (private copy, no event emission) ------------------
    try:
        rover = Rover(terrain=terrain, start=start, config=config)
    except ValueError as exc:
        logger.debug("Rover init failed at start %s: %s", start, exc)
        return ([start], 0.0, -1.0, 0)

    cells_walked = 0
    for cell in full_path[1:]:
        try:
            rover.step_to(cell)
            cells_walked += 1
        except RoverFailure as exc:
            logger.debug("RoverFailure at cell %s after %d steps: %s", cell, cells_walked, exc)
            return (full_path, rover.clock_s, -1.0, cells_walked)

    return (full_path, rover.clock_s, rover.battery_pct, cells_walked)


def evaluate_plan(
    plan_data: tuple[list[tuple[int, int]], float, float, int],
    constraints: MissionConstraints,
) -> tuple[bool, str]:
    """Evaluate dry-run results against mission constraints.

    Args:
        plan_data: 4-tuple returned by :func:`dry_run_mission`
            ``(full_path, duration_s, final_battery_pct, distance_cells)``.
        constraints: Operational constraints to check against.

    Returns:
        A ``(is_feasible, reason)`` pair where *is_feasible* is ``True`` when
        all constraints are satisfied and *reason* is a short human-readable
        explanation of the outcome (pass or specific failure).
    """
    _path, duration_s, final_battery_pct, _cells = plan_data

    # Battery failure signal
    if final_battery_pct < 0.0:
        return (False, "A* path not found or rover battery exhausted during simulation")

    # Minimum battery constraint
    if final_battery_pct < constraints.min_battery_pct:
        return (
            False,
            (
                f"Final battery {final_battery_pct:.1f}% is below minimum "
                f"{constraints.min_battery_pct:.1f}%"
            ),
        )

    # Optional duration constraint
    if constraints.max_duration_s is not None and duration_s > constraints.max_duration_s:
        return (
            False,
            (
                f"Predicted duration {duration_s:.1f} s exceeds maximum "
                f"{constraints.max_duration_s:.1f} s"
            ),
        )

    return (
        True,
        (
            f"Plan feasible: battery={final_battery_pct:.1f}% "
            f"(min={constraints.min_battery_pct:.1f}%), "
            f"duration={duration_s:.1f} s"
        ),
    )
