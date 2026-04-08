"""Cost functions for rover path planning.

Provides pluggable cost functions that map terrain cells to traversal cost
scalars.  These functions conform to the signature::

    cost_fn(terrain: Terrain, row: int, col: int) -> float

and are passed as arguments to :func:`~marsops.planner.astar.astar`.
"""

from __future__ import annotations

from marsops.terrain.loader import Terrain

__all__ = ["terrain_cost"]


def terrain_cost(terrain: Terrain, row: int, col: int) -> float:
    """Compute the traversal cost for a terrain cell based on local slope.

    Uses the slope-squared cost formula::

        cost = 1.0 + (slope_deg / 10.0) ** 2

    A flat cell (slope = 0°) costs exactly 1.0.  A cell at 10° costs 2.0,
    at 20° costs 5.0, and at 30° costs 10.0.  The quadratic growth strongly
    discourages steep traversal paths, biasing the planner toward flat routes
    while never making any traversable cell infinitely expensive.

    This is a toy model inspired by the slope-squared cost heuristics used in
    planetary rover path planners (e.g., the JPL GESTALT hazard-assessment
    system and the MER/MSL onboard traverse cost maps), where energy expenditure
    scales super-linearly with slope angle.

    Args:
        terrain: The elevation grid being planned over.
        row: Row index of the cell.
        col: Column index of the cell.

    Returns:
        Traversal cost as a float ≥ 1.0.
    """
    slope_deg = terrain.slope_at(row, col)
    return 1.0 + (slope_deg / 10.0) ** 2
