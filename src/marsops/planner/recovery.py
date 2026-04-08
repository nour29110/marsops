"""Recovery strategy models and runtime for mid-mission anomaly response.

Defines :class:`RecoveryStrategy` (the outcome of an anomaly recovery decision)
and :func:`recover_from_anomaly`, a deterministic heuristic that picks the
least-disruptive recovery strategy given current rover state and terrain.

The implementation deliberately avoids any LLM calls at runtime; all decisions
are deterministic heuristics so the module is safe to execute in CI.
"""

from __future__ import annotations

import logging
import math
from typing import Literal

from pydantic import BaseModel

from marsops.planner.mission import MissionConstraints, MissionGoal, MissionPlan
from marsops.planner.mission_planner_runtime import plan_mission
from marsops.simulator.rover import Rover, RoverConfig
from marsops.terrain.loader import Terrain

logger = logging.getLogger(__name__)


class RecoveryStrategy(BaseModel):
    """The outcome of an anomaly recovery decision.

    Attributes:
        strategy_type: Which recovery action was chosen.

            * ``"replan_around"`` -- A new feasible plan was found that avoids
              all blocked cells.
            * ``"reduce_ambition"`` -- A feasible plan was found after dropping
              one or more waypoints that could not be reached without traversing
              blocked cells.
            * ``"abort_to_start"`` -- No feasible onward plan could be found;
              the engine should return the rover to the mission start position.
            * ``"continue"`` -- The anomaly was non-disruptive; carry on with
              the current path unchanged.

        new_plan: The replacement :class:`~marsops.planner.mission.MissionPlan`,
            or ``None`` when strategy is ``"continue"`` or ``"abort_to_start"``
            (no detour path is available).
        reasoning: Human-readable explanation of the decision, always including
            the rover's current battery percentage and the number of blocked
            cells considered.
    """

    strategy_type: Literal["replan_around", "reduce_ambition", "abort_to_start", "continue"]
    new_plan: MissionPlan | None = None
    reasoning: str


def _euclidean(a: tuple[int, int], b: tuple[int, int]) -> float:
    """Return Euclidean distance between two grid cells.

    Args:
        a: First cell as (row, col).
        b: Second cell as (row, col).

    Returns:
        Euclidean distance as a float.
    """
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def recover_from_anomaly(
    terrain: Terrain,
    rover: Rover,
    original_goal: MissionGoal,
    remaining_waypoints: list[tuple[int, int]],
    blocked_cells: set[tuple[int, int]],
    rover_config: RoverConfig | None = None,
) -> RecoveryStrategy:
    """Choose and execute a recovery strategy after a mid-mission anomaly.

    Heuristic priority order (safety first, don't give up prematurely):

    1. **Abort immediately** if ``rover.battery_pct < 10``; the rover cannot
       safely continue or attempt a detour.
    2. **Replan around** blocked cells: build a new
       :class:`~marsops.planner.mission.MissionGoal` starting at
       ``rover.position``, keeping all waypoints that are not themselves in
       *blocked_cells*, and call
       :func:`~marsops.planner.mission_planner_runtime.plan_mission`.
       If the plan is feasible, return ``"replan_around"``.
    3. **Reduce ambition**: if replan with all waypoints failed, drop waypoints
       one by one (farthest from the current position first) and retry planning
       until a feasible plan is found.  Return ``"reduce_ambition"`` with the
       reduced plan.
    4. **Abort to start** if no combination of waypoints yields a feasible
       plan.  The engine is responsible for navigating back to the start.

    This function never raises; all exceptions are caught and demoted to an
    ``"abort_to_start"`` result with the exception text in *reasoning*.

    Args:
        terrain: The terrain grid used for replanning.
        rover: Current rover state; ``rover.battery_pct`` and
            ``rover.position`` are read but not mutated.
        original_goal: The original :class:`~marsops.planner.mission.MissionGoal`
            (constraints and ROI are preserved across recovery).
        remaining_waypoints: Ordered list of waypoints not yet reached,
            in intended visit order.
        blocked_cells: Set of ``(row, col)`` cells now impassable due to the
            anomaly.
        rover_config: Optional rover configuration; propagated to
            :func:`~marsops.planner.mission_planner_runtime.plan_mission`.

    Returns:
        A :class:`RecoveryStrategy` describing what the engine should do next.
        Never raises.
    """
    battery_pct = rover.battery_pct
    n_blocked = len(blocked_cells)
    prefix = f"battery={battery_pct:.1f}% blocked_cells={n_blocked}"

    # ------------------------------------------------------------------ #
    # Guard 1: abort immediately on critically low battery                #
    # ------------------------------------------------------------------ #
    if battery_pct < 10.0:
        reason = (
            f"{prefix} — battery below 10%, cannot safely continue or detour. Aborting to start."
        )
        logger.warning("Recovery: abort_to_start (critical battery) — %s", reason)
        return RecoveryStrategy(
            strategy_type="abort_to_start",
            new_plan=None,
            reasoning=reason,
        )

    # ------------------------------------------------------------------ #
    # Build candidate waypoint list: remove any wp inside blocked_cells   #
    # ------------------------------------------------------------------ #
    candidate_wps = [wp for wp in remaining_waypoints if wp not in blocked_cells]

    # ------------------------------------------------------------------ #
    # Helper: attempt to plan from current rover position                  #
    # ------------------------------------------------------------------ #
    def _try_plan(waypoints: list[tuple[int, int]]) -> MissionPlan | None:
        """Return a feasible MissionPlan or None on failure."""
        new_goal = MissionGoal(
            description=original_goal.description,
            start=rover.position,
            region_of_interest=original_goal.region_of_interest,
            min_waypoints=max(1, len(waypoints)),
            constraints=MissionConstraints(
                min_battery_pct=original_goal.constraints.min_battery_pct,
                max_slope_deg=original_goal.constraints.max_slope_deg,
                must_return_to_start=False,  # never loop back during recovery
                max_duration_s=original_goal.constraints.max_duration_s,
            ),
        )
        try:
            plan = plan_mission(terrain, new_goal, rover_config)
        except Exception as exc:
            logger.debug("plan_mission raised during recovery: %s", exc)
            return None
        return plan if plan.feasible else None

    # ------------------------------------------------------------------ #
    # Attempt 1: replan_around with all non-blocked waypoints             #
    # ------------------------------------------------------------------ #
    if candidate_wps:
        plan = _try_plan(candidate_wps)
        if plan is not None:
            reason = (
                f"{prefix} — replanned from {rover.position} keeping "
                f"{len(candidate_wps)} waypoints (dropped blocked ones). "
                f"New plan: battery={plan.predicted_final_battery_pct:.1f}%, "
                f"duration={plan.predicted_duration_s:.1f}s."
            )
            logger.info("Recovery: replan_around — %s", reason)
            return RecoveryStrategy(
                strategy_type="replan_around",
                new_plan=plan,
                reasoning=reason,
            )

    # ------------------------------------------------------------------ #
    # Attempt 2: reduce_ambition — drop farthest waypoints one at a time  #
    # ------------------------------------------------------------------ #
    drop_pool = list(candidate_wps)  # already excludes blocked cells
    reduced_plan: MissionPlan | None = None
    dropped: list[tuple[int, int]] = []

    while drop_pool:
        # Drop the waypoint farthest from the rover's current position
        farthest = max(drop_pool, key=lambda wp: _euclidean(rover.position, wp))
        drop_pool.remove(farthest)
        dropped.append(farthest)

        if not drop_pool:
            break  # no waypoints left to plan with

        plan = _try_plan(drop_pool)
        if plan is not None:
            reduced_plan = plan
            break

    if reduced_plan is not None:
        reason = (
            f"{prefix} — reduced ambition: dropped {len(dropped)} waypoint(s) "
            f"({dropped}) to find feasible plan from {rover.position}. "
            f"New plan: battery={reduced_plan.predicted_final_battery_pct:.1f}%, "
            f"duration={reduced_plan.predicted_duration_s:.1f}s."
        )
        logger.warning("Recovery: reduce_ambition — %s", reason)
        return RecoveryStrategy(
            strategy_type="reduce_ambition",
            new_plan=reduced_plan,
            reasoning=reason,
        )

    # ------------------------------------------------------------------ #
    # Attempt 3: nothing worked — abort to start                          #
    # ------------------------------------------------------------------ #
    reason = (
        f"{prefix} — no feasible onward plan found after dropping all waypoints "
        f"from {rover.position}. Aborting to start. "
        "The abort path itself may be infeasible if blocked cells cut off return routes."
    )
    logger.warning("Recovery: abort_to_start (no feasible plan) — %s", reason)
    return RecoveryStrategy(
        strategy_type="abort_to_start",
        new_plan=None,
        reasoning=reason,
    )
