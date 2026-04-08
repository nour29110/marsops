"""Mission goal, constraint, and plan models for the Mars rover planner.

Defines the Pydantic models that describe a natural-language mission goal,
the operational constraints that must be respected, and the final validated
:class:`MissionPlan` produced by the planning pipeline.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MissionConstraints(BaseModel):
    """Operational constraints that every mission plan must satisfy.

    Attributes:
        min_battery_pct: Minimum acceptable predicted final battery percentage.
            The planner will reject any plan whose dry-run ends below this level.
        max_slope_deg: Maximum terrain slope in degrees the rover may traverse.
            Passed through to the A* planner and traversability checks.
        must_return_to_start: If True the planner appends the start cell as a
            final waypoint so the rover loops back to its launch position.
        max_duration_s: Optional cap on predicted mission duration in seconds.
            ``None`` means no time constraint.
    """

    min_battery_pct: float = 20.0
    max_slope_deg: float = 25.0
    must_return_to_start: bool = False
    max_duration_s: float | None = None


class MissionGoal(BaseModel):
    """Natural-language mission goal with spatial and constraint context.

    Attributes:
        description: Free-text mission goal, e.g.
            ``"survey 3 sites in the north and return"``.  Keywords in this
            string drive the waypoint-selection heuristic (see
            :mod:`marsops.planner.mission_planner_runtime`).
        start: Starting grid cell as ``(row, col)``.
        region_of_interest: Optional bounding box ``(row_min, col_min,
            row_max, col_max)`` restricting where waypoints may be placed.
            When ``None`` the full terrain grid is eligible.
        min_waypoints: Minimum number of distinct waypoints (excluding start)
            the plan must include.
        constraints: Operational constraints; defaults to
            :class:`MissionConstraints` defaults.
    """

    description: str
    start: tuple[int, int]
    region_of_interest: tuple[int, int, int, int] | None = None
    min_waypoints: int = 1
    constraints: MissionConstraints = Field(default_factory=MissionConstraints)


class MissionPlan(BaseModel):
    """Validated, energy-feasible rover mission plan.

    Produced by the mission-planner pipeline after one or more dry-run
    simulation iterations.  All numeric predictions are derived from
    :func:`~marsops.planner.dry_run.dry_run_mission` — never fabricated.

    Attributes:
        goal: The :class:`MissionGoal` this plan addresses.
        waypoints: Ordered visit sequence as ``(row, col)`` cells, excluding
            the start position.
        full_path: Concatenated A* path segments connecting start → wp1 →
            wp2 → … → last waypoint (cell-by-cell).
        predicted_duration_s: Simulated mission duration in seconds.
        predicted_final_battery_pct: Predicted battery percentage at end of
            mission.
        predicted_distance_cells: Total number of cell-to-cell moves in the
            full path.
        feasible: ``True`` if the plan satisfies all :class:`MissionConstraints`;
            ``False`` if no feasible plan was found after the maximum number of
            refinement iterations.
        reasoning: Natural-language explanation of final waypoint choices, any
            trade-offs made, and the dry-run numbers that justified the decision.
    """

    goal: MissionGoal
    waypoints: list[tuple[int, int]]
    full_path: list[tuple[int, int]]
    predicted_duration_s: float
    predicted_final_battery_pct: float
    predicted_distance_cells: int
    feasible: bool
    reasoning: str

    def summary(self) -> str:
        """Return a concise human-readable plan summary for CLI printing.

        Returns:
            Multi-line string describing the plan outcome, waypoints, and
            key predicted metrics.
        """
        status = "FEASIBLE" if self.feasible else "INFEASIBLE"
        lines = [
            f"=== MissionPlan [{status}] ===",
            f"Goal      : {self.goal.description}",
            f"Start     : {self.goal.start}",
            f"Waypoints : {self.waypoints}",
            f"Path cells: {self.predicted_distance_cells}",
            f"Duration  : {self.predicted_duration_s:.1f} s",
            f"Battery   : {self.predicted_final_battery_pct:.1f}% remaining",
            f"Reasoning : {self.reasoning}",
        ]
        return "\n".join(lines)
