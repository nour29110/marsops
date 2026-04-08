"""Runtime mission planner that generates energy-feasible rover traverse plans.

Combines terrain analysis, keyword-driven waypoint selection, nearest-neighbour
TSP ordering, and iterative dry-run refinement to produce a
:class:`~marsops.planner.mission.MissionPlan` that respects all operational
constraints.
"""

from __future__ import annotations

import logging
import math

import numpy as np

from marsops.planner.dry_run import dry_run_mission, evaluate_plan
from marsops.planner.mission import MissionGoal, MissionPlan
from marsops.simulator.rover import RoverConfig
from marsops.terrain.loader import Terrain

logger = logging.getLogger(__name__)

_MAX_REFINEMENT_ITERATIONS: int = 5


def _euclidean(a: tuple[int, int], b: tuple[int, int]) -> float:
    """Return Euclidean distance between two grid cells.

    Args:
        a: First cell as (row, col).
        b: Second cell as (row, col).

    Returns:
        Euclidean distance as a float.
    """
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def _sample_grid_points(
    row_min: int,
    col_min: int,
    row_max: int,
    col_max: int,
    count: int,
) -> list[tuple[int, int]]:
    """Generate deterministic equally-spaced grid sample points in a region.

    Produces approximately *count* points arranged in a rectangular grid
    pattern spanning the given bounding box.  The actual number may differ
    slightly because the grid is rounded to integer side lengths.

    Args:
        row_min: Minimum row (inclusive).
        col_min: Minimum column (inclusive).
        row_max: Maximum row (exclusive).
        col_max: Maximum column (exclusive).
        count: Desired number of sample points.

    Returns:
        List of (row, col) tuples, deterministically ordered row-major.
    """
    height = max(row_max - row_min, 1)
    width = max(col_max - col_min, 1)
    aspect = width / height if height > 0 else 1.0
    n_rows = max(1, int(math.sqrt(count / aspect)))
    n_cols = max(1, math.ceil(count / n_rows))

    row_step = height / (n_rows + 1)
    col_step = width / (n_cols + 1)

    points: list[tuple[int, int]] = []
    for ri in range(1, n_rows + 1):
        for ci in range(1, n_cols + 1):
            r = row_min + int(ri * row_step)
            c = col_min + int(ci * col_step)
            if row_min <= r < row_max and col_min <= c < col_max:
                points.append((r, c))
    return points


def _detect_keywords(description: str) -> list[str]:
    """Extract recognised terrain-selection keywords from a description.

    Args:
        description: Free-text mission goal description.

    Returns:
        List of matched keyword strings (may be empty).
    """
    desc_lower = description.lower()
    matched: list[str] = []
    for kw in ("flat", "high", "low", "delta"):
        if kw in desc_lower:
            matched.append(kw)
    return matched


def plan_mission(
    terrain: Terrain,
    goal: MissionGoal,
    rover_config: RoverConfig | None = None,
) -> MissionPlan:
    """Plan a feasible rover mission given terrain, goal, and constraints.

    Generates candidate waypoints via deterministic grid sampling, filters
    them by terrain keywords found in the goal description, orders them
    using a nearest-neighbour TSP heuristic, and refines the plan through
    up to 5 dry-run iterations — dropping the farthest waypoint on each
    infeasible attempt.

    Args:
        terrain: Elevation grid to plan over.
        goal: Mission goal describing start, region, waypoints, and
            constraints.
        rover_config: Optional rover configuration; defaults to
            :class:`~marsops.simulator.rover.RoverConfig` defaults.

    Returns:
        A :class:`~marsops.planner.mission.MissionPlan` with feasibility
        flag, predicted metrics, and reasoning.  Never raises.
    """
    # -- Determine search region ------------------------------------------------
    if goal.region_of_interest is not None:
        row_min, col_min, row_max, col_max = goal.region_of_interest
    else:
        rows, cols = terrain.shape
        row_min, col_min, row_max, col_max = 0, 0, rows, cols

    # -- Step 1: Candidate generation -------------------------------------------
    sample_count = goal.min_waypoints * 3
    raw_points = _sample_grid_points(
        row_min,
        col_min,
        row_max,
        col_max,
        sample_count,
    )

    max_slope = goal.constraints.max_slope_deg
    traversable_candidates = [
        (r, c) for r, c in raw_points if terrain.is_traversable(r, c, max_slope)
    ]

    # Keyword filtering
    keywords = _detect_keywords(goal.description)
    logger.info("Detected keywords: %s", keywords)

    filtered = traversable_candidates
    if keywords:
        # Compute ROI elevation statistics using numpy for array ops
        roi_elev = terrain.elevation[row_min:row_max, col_min:col_max]
        nodata = terrain.metadata.nodata_value
        valid_mask = ~np.isclose(roi_elev, nodata, atol=1e-6)
        if np.any(valid_mask):
            valid_vals = roi_elev[valid_mask]
            median_elev = float(np.median(valid_vals))
            std_elev = float(np.std(valid_vals))
        else:
            median_elev = 0.0
            std_elev = 0.0

        kw_filtered: list[tuple[int, int]] = []
        for r, c in traversable_candidates:
            keep = True
            elev = terrain.elevation_at(r, c)
            slope = terrain.slope_at(r, c)
            if "flat" in keywords:
                keep = keep and slope < 10.0
            if "high" in keywords:
                keep = keep and elev > median_elev + std_elev
            if "low" in keywords:
                keep = keep and elev < median_elev - std_elev
            if "delta" in keywords:
                keep = keep and elev < median_elev
            if keep:
                kw_filtered.append((r, c))

        if len(kw_filtered) >= goal.min_waypoints:
            filtered = kw_filtered
        else:
            logger.info(
                "Keyword filter left %d candidates (need %d); falling back to all traversable",
                len(kw_filtered),
                goal.min_waypoints,
            )
            filtered = traversable_candidates

    candidates = filtered
    logger.info(
        "Candidate waypoints: %d (from %d sampled, %d traversable)",
        len(candidates),
        len(raw_points),
        len(traversable_candidates),
    )

    # -- Step 2: Select and order waypoints (nearest-neighbour TSP) -------------
    n_select = min(goal.min_waypoints, len(candidates))
    remaining = list(candidates)
    waypoints: list[tuple[int, int]] = []
    current = goal.start

    for _ in range(n_select):
        if not remaining:
            break
        best_idx = 0
        best_dist = math.inf
        for idx, cand in enumerate(remaining):
            d = _euclidean(current, cand)
            if d < best_dist:
                best_dist = d
                best_idx = idx
        chosen = remaining.pop(best_idx)
        waypoints.append(chosen)
        current = chosen

    if goal.constraints.must_return_to_start:
        waypoints.append(goal.start)

    # -- Step 3: Refinement loop ------------------------------------------------
    iterations = 0
    feasible = False
    reason = "no dry-run executed"
    plan_data: tuple[list[tuple[int, int]], float, float, int] = ([goal.start], 0.0, 100.0, 0)

    for iteration in range(_MAX_REFINEMENT_ITERATIONS):
        iterations = iteration + 1
        plan_data = dry_run_mission(
            terrain,
            goal.start,
            waypoints,
            rover_config,
        )
        feasible, reason = evaluate_plan(plan_data, goal.constraints)
        logger.info(
            "Refinement iteration %d: feasible=%s, reason=%s",
            iterations,
            feasible,
            reason,
        )
        if feasible:
            break

        # Drop the farthest non-start waypoint from goal.start
        # When must_return_to_start, the last waypoint is goal.start — keep it.
        droppable = waypoints[:-1] if goal.constraints.must_return_to_start else list(waypoints)

        if not droppable:
            logger.info("No droppable waypoints remain; stopping refinement")
            break

        farthest_wp = max(droppable, key=lambda w: _euclidean(goal.start, w))
        waypoints.remove(farthest_wp)
        logger.info("Dropped waypoint %s (farthest from start)", farthest_wp)

    # -- Step 4: Construct MissionPlan ------------------------------------------
    full_path, duration_s, final_battery_pct, distance_cells = plan_data

    kw_str = ", ".join(keywords) if keywords else "none"
    reasoning = (
        f"Keywords matched: [{kw_str}]. "
        f"Candidates found: {len(candidates)}. "
        f"Refinement iterations: {iterations}. "
        f"Final dry-run: battery={final_battery_pct:.1f}%, "
        f"duration={duration_s:.1f}s."
    )

    return MissionPlan(
        goal=goal,
        waypoints=waypoints,
        full_path=full_path,
        predicted_duration_s=duration_s,
        predicted_final_battery_pct=final_battery_pct,
        predicted_distance_cells=distance_cells,
        feasible=feasible,
        reasoning=reasoning,
    )
