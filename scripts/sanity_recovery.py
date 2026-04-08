"""Sanity check script for the anomaly recovery runtime.

Builds a small synthetic flat Terrain, exercises two representative recovery
scenarios, and asserts that the heuristic behaves as specified.

Run with::

    uv run python scripts/sanity_recovery.py
"""

from __future__ import annotations

import logging
import sys

import numpy as np

from marsops.planner.mission import MissionConstraints, MissionGoal
from marsops.planner.recovery import recover_from_anomaly
from marsops.simulator.rover import Rover, RoverConfig
from marsops.terrain.loader import Terrain, TerrainMetadata

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared terrain: 15x15 flat grid at constant 10 m elevation
# ---------------------------------------------------------------------------

_ROWS = 15
_COLS = 15


def _build_terrain() -> Terrain:
    """Return a small 15x15 flat synthetic terrain.

    All cells are set to 10.0 m elevation (slope = 0).  Resolution is 18 m,
    nodata sentinel is -9999.0, and geographic bounds span (0, 0, 1, 1).

    Returns:
        A :class:`~marsops.terrain.loader.Terrain` ready for planning.
    """
    elevation = np.full((_ROWS, _COLS), 10.0, dtype=np.float32)
    meta = TerrainMetadata(
        name="sanity-flat-15x15",
        source_url="synthetic",
        resolution_m=18.0,
        bounds=(0.0, 0.0, 1.0, 1.0),
        shape=(_ROWS, _COLS),
        nodata_value=-9999.0,
    )
    return Terrain(elevation=elevation, metadata=meta)


def _build_goal(start: tuple[int, int]) -> MissionGoal:
    """Return a basic mission goal starting at *start*.

    Args:
        start: Starting grid cell ``(row, col)``.

    Returns:
        A :class:`~marsops.planner.mission.MissionGoal`.
    """
    return MissionGoal(
        description="flat survey",
        start=start,
        region_of_interest=None,
        min_waypoints=1,
        constraints=MissionConstraints(
            min_battery_pct=20.0,
            max_slope_deg=25.0,
            must_return_to_start=False,
            max_duration_s=None,
        ),
    )


# ---------------------------------------------------------------------------
# Case 1: Low-battery abort
# ---------------------------------------------------------------------------


def case1_low_battery_abort(terrain: Terrain) -> None:
    """Assert that a critically-low battery triggers abort_to_start.

    Creates a rover at (2, 2) with default config, drains battery to 1 % of
    capacity, and calls :func:`recover_from_anomaly`.  Asserts that the
    returned strategy is ``"abort_to_start"``.

    Args:
        terrain: Shared 15x15 flat terrain.

    Raises:
        AssertionError: If the strategy is not ``"abort_to_start"``.
    """
    config = RoverConfig()
    rover = Rover(terrain=terrain, start=(2, 2), config=config)
    # Drain to 1 % of capacity
    rover.battery_wh = config.battery_capacity_wh * 0.01

    goal = _build_goal(start=(2, 2))

    strategy = recover_from_anomaly(
        terrain=terrain,
        rover=rover,
        original_goal=goal,
        remaining_waypoints=[(10, 10)],
        blocked_cells=set(),
        rover_config=None,
    )

    logger.info("Case 1 result: %s | %s", strategy.strategy_type, strategy.reasoning)

    assert strategy.strategy_type == "abort_to_start", (
        f"Expected abort_to_start, got {strategy.strategy_type!r}"
    )
    logger.info("Case 1 PASSED — abort_to_start on critically low battery.")


# ---------------------------------------------------------------------------
# Case 2: Blocked waypoint replan
# ---------------------------------------------------------------------------


def case2_blocked_waypoint_replan(terrain: Terrain) -> None:
    """Assert that a blocked waypoint triggers replanning or ambition reduction.

    Creates a fresh rover at (2, 2) with full battery.  One of the two
    remaining waypoints — (5, 5) — is blocked.  Calls
    :func:`recover_from_anomaly` and asserts the strategy is either
    ``"replan_around"`` or ``"reduce_ambition"`` with a non-None new plan.

    Args:
        terrain: Shared 15x15 flat terrain.

    Raises:
        AssertionError: If the strategy is unexpected or ``new_plan`` is None.
    """
    config = RoverConfig()
    rover = Rover(terrain=terrain, start=(2, 2), config=config)
    # Full battery — no forced abort

    goal = _build_goal(start=(2, 2))

    strategy = recover_from_anomaly(
        terrain=terrain,
        rover=rover,
        original_goal=goal,
        remaining_waypoints=[(5, 5), (10, 10)],
        blocked_cells={(5, 5)},
        rover_config=None,
    )

    logger.info("Case 2 result: %s | %s", strategy.strategy_type, strategy.reasoning)

    assert strategy.strategy_type in ("replan_around", "reduce_ambition"), (
        f"Expected replan_around or reduce_ambition, got {strategy.strategy_type!r}"
    )
    assert strategy.new_plan is not None, (
        f"Expected a non-None new_plan for strategy {strategy.strategy_type!r}"
    )
    logger.info("Case 2 PASSED — %s with a valid new plan.", strategy.strategy_type)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run both sanity cases and log the overall result.

    Exits with status code 1 if any assertion fails.
    """
    terrain = _build_terrain()
    logger.info("Built 15x15 flat terrain (resolution=18 m).")

    try:
        case1_low_battery_abort(terrain)
        case2_blocked_waypoint_replan(terrain)
    except AssertionError as exc:
        logger.error("SANITY CHECK FAILED: %s", exc)
        sys.exit(1)

    logger.info("SANITY CHECK PASSED")


if __name__ == "__main__":
    main()
