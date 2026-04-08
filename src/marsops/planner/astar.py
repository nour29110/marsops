"""A* pathfinding on Mars terrain grids.

Implements an 8-connected A* search over a :class:`~marsops.terrain.loader.Terrain`
grid.  Diagonal moves cost sqrt(2) times the pluggable cost function; straight
moves cost 1.0.  The octile-distance heuristic is admissible for 8-connected grids.
"""

from __future__ import annotations

import heapq
import logging
import math
from collections.abc import Callable

from marsops.terrain.loader import Terrain

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

Coord = tuple[int, int]
"""A (row, col) grid coordinate."""

_SQRT2 = math.sqrt(2.0)


def _in_bounds(r: int, c: int, rows: int, cols: int) -> bool:
    """Return True if (r, c) lies within a grid of shape (rows, cols).

    Args:
        r: Row index.
        c: Column index.
        rows: Total row count of the grid.
        cols: Total column count of the grid.

    Returns:
        True when 0 <= r < rows and 0 <= c < cols.
    """
    return 0 <= r < rows and 0 <= c < cols


# 8-connected neighbours: (delta_row, delta_col, move_cost_multiplier)
_NEIGHBOURS: list[tuple[int, int, float]] = [
    (-1, 0, 1.0),
    (1, 0, 1.0),
    (0, -1, 1.0),
    (0, 1, 1.0),
    (-1, -1, _SQRT2),
    (-1, 1, _SQRT2),
    (1, -1, _SQRT2),
    (1, 1, _SQRT2),
]


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class NoPathFoundError(Exception):
    """Raised when A* exhausts the search space without reaching the goal.

    Attributes:
        message: Human-readable description including start and goal coordinates.
    """


# ---------------------------------------------------------------------------
# Heuristic
# ---------------------------------------------------------------------------


def _octile_distance(row: int, col: int, goal_row: int, goal_col: int) -> float:
    """Compute the octile distance heuristic for an 8-connected grid.

    Admissible because it never over-estimates the true cost (which uses the
    same √2 diagonal weight).

    Args:
        row: Current cell row.
        col: Current cell column.
        goal_row: Goal cell row.
        goal_col: Goal cell column.

    Returns:
        Octile distance as a float.
    """
    dx = abs(col - goal_col)
    dy = abs(row - goal_row)
    return dx + dy + (_SQRT2 - 2.0) * min(dx, dy)


# ---------------------------------------------------------------------------
# A* search
# ---------------------------------------------------------------------------


def astar(
    terrain: Terrain,
    start: Coord,
    goal: Coord,
    cost_fn: Callable[[Terrain, int, int], float] | None = None,
    max_slope_deg: float = 25.0,
) -> list[Coord]:
    """Find the least-cost path from *start* to *goal* on *terrain* using A*.

    Performs an 8-connected A* search.  Diagonal moves cost sqrt(2) * the cell
    cost; cardinal moves cost 1.0 * the cell cost.  The search respects the
    rover's slope limit via :meth:`~marsops.terrain.loader.Terrain.is_traversable`.

    Args:
        terrain: Elevation grid to plan over.
        start: Source coordinate as ``(row, col)``.
        goal: Destination coordinate as ``(row, col)``.
        cost_fn: Callable ``(terrain, row, col) -> float`` returning the
            traversal cost for a cell (must be ≥ 1).  Defaults to
            :func:`~marsops.planner.cost.terrain_cost`.
        max_slope_deg: Maximum slope in degrees a cell may have to be
            considered traversable.  Default: 25.0 (Curiosity rover limit).

    Returns:
        Ordered list of ``(row, col)`` coordinates from *start* (inclusive)
        to *goal* (inclusive).  A one-element list is returned when
        ``start == goal``.

    Raises:
        ValueError: If *start* or *goal* is out of bounds or non-traversable.
        NoPathFoundError: If no path exists between *start* and *goal* given
            the terrain constraints.
    """
    # Import here to avoid a circular import; cost.py imports nothing from astar.
    from marsops.planner.cost import terrain_cost as _default_cost

    if cost_fn is None:
        cost_fn = _default_cost

    # -- validate start / goal -----------------------------------------------
    rows, cols = terrain.shape
    start_r, start_c = start
    goal_r, goal_c = goal

    if not _in_bounds(start_r, start_c, rows, cols):
        msg = f"start {start} is out of bounds for terrain shape {terrain.shape}"
        raise ValueError(msg)
    if not terrain.is_traversable(start_r, start_c, max_slope_deg):
        msg = f"start {start} is not traversable (nodata or slope > {max_slope_deg}°)"
        raise ValueError(msg)
    if not _in_bounds(goal_r, goal_c, rows, cols):
        msg = f"goal {goal} is out of bounds for terrain shape {terrain.shape}"
        raise ValueError(msg)
    if not terrain.is_traversable(goal_r, goal_c, max_slope_deg):
        msg = f"goal {goal} is not traversable (nodata or slope > {max_slope_deg}°)"
        raise ValueError(msg)

    # -- trivial case --------------------------------------------------------
    if start == goal:
        return [start]

    # -- A* ------------------------------------------------------------------
    # open_set heap entries: (f_score, g_score, row, col)
    h_start = _octile_distance(start_r, start_c, goal_r, goal_c)
    open_set: list[tuple[float, float, int, int]] = []
    heapq.heappush(open_set, (h_start, 0.0, start_r, start_c))

    came_from: dict[Coord, Coord] = {}
    g_score: dict[Coord, float] = {start: 0.0}

    while open_set:
        _f, g_current, cur_r, cur_c = heapq.heappop(open_set)
        current: Coord = (cur_r, cur_c)

        if current == goal:
            return _reconstruct_path(came_from, current)

        # Skip stale entries: a node may be pushed multiple times when a cheaper
        # path is found later.  Strict `>` (not `>=`) is intentional — equal
        # g-scores mean two paths tied in cost, so we expand rather than skip.
        if g_current > g_score.get(current, math.inf):
            continue

        for dr, dc, move_mult in _NEIGHBOURS:
            nb_r, nb_c = cur_r + dr, cur_c + dc
            nb: Coord = (nb_r, nb_c)

            if not terrain.is_traversable(nb_r, nb_c, max_slope_deg):
                continue

            cell_cost = cost_fn(terrain, nb_r, nb_c)
            tentative_g = g_current + move_mult * cell_cost

            if tentative_g < g_score.get(nb, math.inf):
                g_score[nb] = tentative_g
                came_from[nb] = current
                h = _octile_distance(nb_r, nb_c, goal_r, goal_c)
                heapq.heappush(open_set, (tentative_g + h, tentative_g, nb_r, nb_c))

    msg = f"No path found from {start} to {goal}"
    raise NoPathFoundError(msg)


# ---------------------------------------------------------------------------
# Path reconstruction
# ---------------------------------------------------------------------------


def _reconstruct_path(came_from: dict[Coord, Coord], current: Coord) -> list[Coord]:
    """Walk back through *came_from* to reconstruct the path.

    Args:
        came_from: Mapping from each visited node to its predecessor.
        current: The goal node to trace back from.

    Returns:
        Ordered list of coordinates from start to current (inclusive).
    """
    path: list[Coord] = [current]
    while current in came_from:
        current = came_from[current]
        path.append(current)
    path.reverse()
    return path
