"""Path statistics helpers for rover mission planning.

Provides utilities for computing summary metrics over a planned path, such
as total traversal cost, elevation range, and step count.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from marsops.terrain.loader import Terrain


def compute_path_cost(
    terrain: Terrain,
    path: list[tuple[int, int]],
    cost_fn: Callable[[Terrain, int, int], float],
) -> float:
    """Compute the total weighted traversal cost of a planned path.

    Accumulates the move cost for each step along *path*.  Diagonal moves
    (where both row and column change by 1) are weighted by sqrt(2); cardinal
    moves are weighted by 1.0.  The cell cost at the *destination* cell of
    each move is used (the start cell is not counted).

    Args:
        terrain: Elevation grid the path was planned over.
        path: Ordered list of ``(row, col)`` coordinates.
        cost_fn: Callable ``(terrain, row, col) -> float`` returning the
            traversal cost for a cell.

    Returns:
        Total weighted path cost as a float.  Returns 0.0 for a one-cell path.
    """
    total = 0.0
    for i in range(len(path) - 1):
        (r1, c1), (r2, c2) = path[i], path[i + 1]
        move_mult = math.sqrt(2.0) if abs(r2 - r1) + abs(c2 - c1) == 2 else 1.0
        total += move_mult * cost_fn(terrain, r2, c2)
    return total


def path_elevation_range(
    terrain: Terrain,
    path: list[tuple[int, int]],
) -> tuple[float, float]:
    """Return the minimum and maximum elevation along a path.

    Args:
        terrain: Elevation grid the path traverses.
        path: Ordered list of ``(row, col)`` coordinates.

    Returns:
        Tuple ``(min_elevation, max_elevation)`` in metres.

    Raises:
        ValueError: If *path* is empty.
    """
    if not path:
        msg = "path must not be empty"
        raise ValueError(msg)
    elevations = [terrain.elevation_at(r, c) for r, c in path]
    return min(elevations), max(elevations)
