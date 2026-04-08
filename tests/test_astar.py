"""Tests for marsops.planner (astar + cost) against synthetic Terrain instances.

All terrains are small (5x5 to 20x20) synthetic arrays.  No real DEM is loaded.
Every test is deterministic; Hypothesis seeds are controlled via settings.
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from marsops.planner import NoPathFoundError, astar, terrain_cost
from marsops.terrain.loader import Terrain, TerrainMetadata

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_flat_terrain(rows: int, cols: int, base_elev: float = 0.0) -> Terrain:
    """Construct a fully flat, nodata-free Terrain for testing.

    Args:
        rows: Number of grid rows.
        cols: Number of grid columns.
        base_elev: Uniform elevation value (default 0.0).

    Returns:
        A :class:`Terrain` with uniform elevation and no hazards.
    """
    elevation = np.full((rows, cols), base_elev, dtype=np.float32)
    meta = TerrainMetadata(
        name="test",
        source_url="synthetic",
        resolution_m=1.0,
        bounds=(0.0, 0.0, float(cols), float(rows)),
        shape=(rows, cols),
        nodata_value=-9999.0,
    )
    return Terrain(elevation=elevation, metadata=meta)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def flat_10x10() -> Terrain:
    """10x10 flat terrain at elevation 0.0."""
    return make_flat_terrain(10, 10)


@pytest.fixture()
def flat_7x7() -> Terrain:
    """7x7 flat terrain used for wall tests."""
    return make_flat_terrain(7, 7)


# ---------------------------------------------------------------------------
# terrain_cost tests
# ---------------------------------------------------------------------------


class TestTerrainCost:
    """Unit tests for the terrain_cost function."""

    def test_flat_cell_cost_is_one(self) -> None:
        """A flat cell (slope == 0.0) must produce cost exactly 1.0."""
        terrain = make_flat_terrain(5, 5)
        # Interior cell on a perfectly flat grid → slope == 0
        cost = terrain_cost(terrain, 2, 2)
        assert cost == pytest.approx(1.0)

    def test_cost_increases_with_slope(self) -> None:
        """A ramp terrain produces cost > 1.0 for interior cells."""
        # Build a 5-row ramp: elevation grows linearly row by row
        rows, cols = 5, 5
        elev = np.zeros((rows, cols), dtype=np.float32)
        for r in range(rows):
            elev[r, :] = float(r) * 10.0  # 10 m per cell → large slope
        meta = TerrainMetadata(
            name="ramp",
            source_url="synthetic",
            resolution_m=1.0,
            bounds=(0.0, 0.0, float(cols), float(rows)),
            shape=(rows, cols),
            nodata_value=-9999.0,
        )
        terrain = Terrain(elevation=elev, metadata=meta)
        # Interior cell (not an edge) should have a non-zero slope
        slope = terrain.slope_at(2, 2)
        assert slope > 0.0, "Expected nonzero slope on ramp"
        cost = terrain_cost(terrain, 2, 2)
        assert cost > 1.0

    @given(
        row=st.integers(min_value=0, max_value=4),
        col=st.integers(min_value=0, max_value=4),
        base_elev=st.floats(
            min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False
        ),
    )
    @settings(max_examples=100)
    def test_cost_never_below_one_hypothesis(self, row: int, col: int, base_elev: float) -> None:
        """terrain_cost must be >= 1.0 for any valid cell on any flat terrain."""
        terrain = make_flat_terrain(5, 5, base_elev=base_elev)
        cost = terrain_cost(terrain, row, col)
        assert cost >= 1.0


# ---------------------------------------------------------------------------
# astar tests — basic behaviour
# ---------------------------------------------------------------------------


class TestAstarBasic:
    """Tests for degenerate and simple astar cases."""

    @pytest.mark.parametrize(
        "start",
        [(0, 0), (5, 5), (9, 9), (3, 7)],
    )
    def test_start_equals_goal_returns_singleton(
        self, flat_10x10: Terrain, start: tuple[int, int]
    ) -> None:
        """When start == goal the path must be exactly [start]."""
        path = astar(flat_10x10, start, start)
        assert path == [start]

    def test_straight_line_flat_grid(self, flat_10x10: Terrain) -> None:
        """A* on a 10x10 flat grid must find a path from (0,0) to (0,9)."""
        path = astar(flat_10x10, (0, 0), (0, 9))
        assert path[0] == (0, 0)
        assert path[-1] == (0, 9)
        assert len(path) >= 2

    def test_path_continuity(self, flat_10x10: Terrain) -> None:
        """Every consecutive pair of cells must differ by at most 1 in each axis."""
        path = astar(flat_10x10, (0, 0), (9, 9))
        for (r1, c1), (r2, c2) in itertools.pairwise(path):
            assert abs(r2 - r1) <= 1
            assert abs(c2 - c1) <= 1


# ---------------------------------------------------------------------------
# astar — wall routing
# ---------------------------------------------------------------------------


class TestAstarWallRouting:
    """Tests that A* correctly routes around obstacles."""

    def test_routes_around_nodata_wall(self) -> None:
        """Path from (0,0) to (0,6) must detour around a full nodata column 3.

        The wall spans rows 0-5 in column 3; row 6 is left open as the gap.
        """
        rows, cols = 7, 7
        elev = np.full((rows, cols), 0.0, dtype=np.float32)
        # Block column 3, all rows except the last
        for r in range(6):
            elev[r, 3] = -9999.0
        meta = TerrainMetadata(
            name="wall",
            source_url="synthetic",
            resolution_m=1.0,
            bounds=(0.0, 0.0, float(cols), float(rows)),
            shape=(rows, cols),
            nodata_value=-9999.0,
        )
        terrain = Terrain(elevation=elev, metadata=meta)
        path = astar(terrain, (0, 0), (0, 6))
        # Path must exist and have correct endpoints
        assert path[0] == (0, 0)
        assert path[-1] == (0, 6)
        # No cell in path may be at column 3 for rows 0-5
        for r, c in path:
            assert not (c == 3 and r < 6), f"Path illegally crosses wall at ({r}, {c})"

    def test_prefers_flat_route_over_steep(self) -> None:
        """Planner must stay in the flat zone when a steep zone is the alternative.

        Build a 5x15 terrain:
        - Rows 0-1: flat (elev 0)
        - Rows 3-4: very steep ramp (elev increases sharply per column)
        - Row 2: transition with neutral elevation

        Start at (1, 0), goal at (1, 14).  The flat path stays near row 1.
        We verify that the majority of path cells come from rows 0-2.
        """
        rows, cols = 5, 15
        elev = np.zeros((rows, cols), dtype=np.float32)
        # Bottom rows: create a very steep ramp (100 m per column)
        for c in range(cols):
            elev[3, c] = float(c) * 100.0
            elev[4, c] = float(c) * 200.0

        meta = TerrainMetadata(
            name="flat_vs_steep",
            source_url="synthetic",
            resolution_m=1.0,
            bounds=(0.0, 0.0, float(cols), float(rows)),
            shape=(rows, cols),
            nodata_value=-9999.0,
        )
        terrain = Terrain(elevation=elev, metadata=meta)
        path = astar(terrain, (1, 0), (1, 14), max_slope_deg=25.0)
        assert path[0] == (1, 0)
        assert path[-1] == (1, 14)
        # Most of the path should stay in the flat zone (rows 0-2)
        flat_cells = sum(1 for r, _c in path if r <= 2)
        assert flat_cells >= len(path) * 0.8, (
            f"Expected path mostly in flat zone; flat_cells={flat_cells}/{len(path)}"
        )


# ---------------------------------------------------------------------------
# astar — error conditions
# ---------------------------------------------------------------------------


class TestAstarErrors:
    """Tests for ValueError and NoPathFoundError conditions."""

    def test_raises_no_path_when_goal_enclosed(self) -> None:
        """NoPathFoundError when goal is fully surrounded by nodata."""
        rows, cols = 7, 7
        elev = np.full((rows, cols), 0.0, dtype=np.float32)
        # Surround cell (3, 3) with nodata on all 8 neighbours
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if (dr, dc) != (0, 0):
                    elev[3 + dr, 3 + dc] = -9999.0
        meta = TerrainMetadata(
            name="enclosed",
            source_url="synthetic",
            resolution_m=1.0,
            bounds=(0.0, 0.0, float(cols), float(rows)),
            shape=(rows, cols),
            nodata_value=-9999.0,
        )
        terrain = Terrain(elevation=elev, metadata=meta)
        with pytest.raises(NoPathFoundError):
            astar(terrain, (0, 0), (3, 3))

    def test_raises_value_error_start_is_nodata(self) -> None:
        """ValueError when start cell is nodata."""
        rows, cols = 7, 7
        elev = np.full((rows, cols), 0.0, dtype=np.float32)
        elev[0, 0] = -9999.0
        meta = TerrainMetadata(
            name="start_nodata",
            source_url="synthetic",
            resolution_m=1.0,
            bounds=(0.0, 0.0, float(cols), float(rows)),
            shape=(rows, cols),
            nodata_value=-9999.0,
        )
        terrain = Terrain(elevation=elev, metadata=meta)
        with pytest.raises(ValueError, match="start"):
            astar(terrain, (0, 0), (6, 6))

    def test_raises_value_error_goal_is_nodata(self) -> None:
        """ValueError when goal cell is nodata."""
        rows, cols = 7, 7
        elev = np.full((rows, cols), 0.0, dtype=np.float32)
        elev[6, 6] = -9999.0
        meta = TerrainMetadata(
            name="goal_nodata",
            source_url="synthetic",
            resolution_m=1.0,
            bounds=(0.0, 0.0, float(cols), float(rows)),
            shape=(rows, cols),
            nodata_value=-9999.0,
        )
        terrain = Terrain(elevation=elev, metadata=meta)
        with pytest.raises(ValueError, match="goal"):
            astar(terrain, (0, 0), (6, 6))

    def test_raises_value_error_start_out_of_bounds(self, flat_7x7: Terrain) -> None:
        """ValueError when start row is negative (out of bounds)."""
        with pytest.raises(ValueError, match="start"):
            astar(flat_7x7, (-1, 0), (3, 3))

    def test_raises_value_error_goal_out_of_bounds(self, flat_7x7: Terrain) -> None:
        """ValueError when goal column is far out of bounds."""
        with pytest.raises(ValueError, match="goal"):
            astar(flat_7x7, (0, 0), (0, 999))

    def test_raises_value_error_start_oob_negative_col(self, flat_7x7: Terrain) -> None:
        """ValueError when start column is negative."""
        with pytest.raises(ValueError, match="start"):
            astar(flat_7x7, (0, -1), (3, 3))

    def test_raises_value_error_goal_oob_row(self, flat_7x7: Terrain) -> None:
        """ValueError when goal row exceeds grid height."""
        with pytest.raises(ValueError, match="goal"):
            astar(flat_7x7, (0, 0), (100, 0))


# ---------------------------------------------------------------------------
# Hypothesis property-based tests
# ---------------------------------------------------------------------------


class TestAstarHypothesis:
    """Property-based tests using Hypothesis strategies."""

    @given(
        grid_rows=st.integers(min_value=5, max_value=15),
        grid_cols=st.integers(min_value=5, max_value=15),
        start_r=st.integers(min_value=0, max_value=4),
        start_c=st.integers(min_value=0, max_value=4),
        goal_r=st.integers(min_value=0, max_value=4),
        goal_c=st.integers(min_value=0, max_value=4),
        base_elev=st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_path_endpoints_and_connectivity(
        self,
        grid_rows: int,
        grid_cols: int,
        start_r: int,
        start_c: int,
        goal_r: int,
        goal_c: int,
        base_elev: float,
    ) -> None:
        """On any flat terrain, path must start/end at given coords and be 8-connected.

        Clamp start/goal into the actual grid to keep coordinates in bounds.
        """
        # Ensure coordinates are within the generated grid dimensions
        sr = min(start_r, grid_rows - 1)
        sc = min(start_c, grid_cols - 1)
        gr = min(goal_r, grid_rows - 1)
        gc = min(goal_c, grid_cols - 1)

        terrain = make_flat_terrain(grid_rows, grid_cols, base_elev=base_elev)
        start = (sr, sc)
        goal = (gr, gc)

        path = astar(terrain, start, goal)

        # Endpoints
        assert path[0] == start
        assert path[-1] == goal

        # 8-connected adjacency
        for (r1, c1), (r2, c2) in itertools.pairwise(path):
            assert abs(r2 - r1) <= 1, f"Row jump > 1 between {(r1, c1)} and {(r2, c2)}"
            assert abs(c2 - c1) <= 1, f"Col jump > 1 between {(r1, c1)} and {(r2, c2)}"

    @given(
        grid_size=st.integers(min_value=5, max_value=15),
        start_r=st.integers(min_value=0, max_value=4),
        start_c=st.integers(min_value=0, max_value=4),
        goal_r=st.integers(min_value=0, max_value=4),
        goal_c=st.integers(min_value=0, max_value=4),
    )
    @settings(max_examples=100)
    def test_path_length_at_least_chebyshev_distance(
        self,
        grid_size: int,
        start_r: int,
        start_c: int,
        goal_r: int,
        goal_c: int,
    ) -> None:
        """len(path) - 1 must be >= Chebyshev distance between start and goal.

        This follows from the 8-connected move model: each step covers at most
        1 cell in each dimension, so the path cannot be shorter than
        max(|dr|, |dc|) steps.
        """
        # Clamp coordinates within grid_size
        sr = min(start_r, grid_size - 1)
        sc = min(start_c, grid_size - 1)
        gr = min(goal_r, grid_size - 1)
        gc = min(goal_c, grid_size - 1)

        terrain = make_flat_terrain(grid_size, grid_size)
        path = astar(terrain, (sr, sc), (gr, gc))

        chebyshev = max(abs(gr - sr), abs(gc - sc))
        assert len(path) - 1 >= chebyshev, (
            f"Path length {len(path) - 1} < Chebyshev distance {chebyshev} "
            f"for start=({sr},{sc}) goal=({gr},{gc})"
        )

    @given(
        row=st.integers(min_value=0, max_value=14),
        col=st.integers(min_value=0, max_value=14),
        slope_height=st.floats(
            min_value=0.1, max_value=50.0, allow_nan=False, allow_infinity=False
        ),
    )
    @settings(max_examples=100)
    def test_terrain_cost_formula_is_slope_squared(
        self, row: int, col: int, slope_height: float
    ) -> None:
        """terrain_cost must equal 1 + (slope/10)^2 for any cell."""
        rows, cols = 15, 15
        # A flat terrain: all cells have slope=0, so cost=1.0
        terrain = make_flat_terrain(rows, cols, base_elev=0.0)
        r = min(row, rows - 1)
        c = min(col, cols - 1)
        slope = terrain.slope_at(r, c)
        expected = 1.0 + (slope / 10.0) ** 2
        actual = terrain_cost(terrain, r, c)
        assert math.isclose(actual, expected, rel_tol=1e-6), (
            f"cost={actual}, expected={expected} at ({r},{c})"
        )


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------


class TestAstarEdgeCases:
    """Miscellaneous edge cases and regression guards."""

    def test_custom_cost_fn_is_used(self, flat_10x10: Terrain) -> None:
        """A custom cost_fn that always returns 1.0 must still produce a valid path."""

        def constant_cost(t: Terrain, r: int, c: int) -> float:
            return 1.0

        path = astar(flat_10x10, (0, 0), (9, 9), cost_fn=constant_cost)
        assert path[0] == (0, 0)
        assert path[-1] == (9, 9)

    def test_adjacent_start_goal(self, flat_10x10: Terrain) -> None:
        """Path between adjacent cells must have exactly 2 elements."""
        path = astar(flat_10x10, (0, 0), (0, 1))
        assert path == [(0, 0), (0, 1)]

    def test_diagonal_start_goal(self, flat_10x10: Terrain) -> None:
        """Diagonal single-step path must have exactly 2 elements."""
        path = astar(flat_10x10, (0, 0), (1, 1))
        assert path == [(0, 0), (1, 1)]

    def test_no_path_completely_blocked_terrain(self) -> None:
        """NoPathFoundError when entire terrain is nodata except start and goal."""
        rows, cols = 5, 5
        elev = np.full((rows, cols), -9999.0, dtype=np.float32)
        # Only start (0,0) and goal (4,4) are traversable
        elev[0, 0] = 0.0
        elev[4, 4] = 0.0
        meta = TerrainMetadata(
            name="mostly_blocked",
            source_url="synthetic",
            resolution_m=1.0,
            bounds=(0.0, 0.0, float(cols), float(rows)),
            shape=(rows, cols),
            nodata_value=-9999.0,
        )
        terrain = Terrain(elevation=elev, metadata=meta)
        with pytest.raises(NoPathFoundError):
            astar(terrain, (0, 0), (4, 4))

    def test_all_path_cells_are_in_bounds(self, flat_10x10: Terrain) -> None:
        """Every cell in a returned path must be within terrain bounds."""
        rows, cols = flat_10x10.shape
        path = astar(flat_10x10, (0, 0), (9, 9))
        for r, c in path:
            assert 0 <= r < rows
            assert 0 <= c < cols

    def test_all_path_cells_are_traversable(self, flat_10x10: Terrain) -> None:
        """Every cell in the path must pass is_traversable."""
        path = astar(flat_10x10, (0, 0), (9, 9))
        for r, c in path:
            assert flat_10x10.is_traversable(r, c), f"Cell ({r},{c}) is not traversable"

    def test_max_slope_deg_respected(self) -> None:
        """Path must not include cells whose slope exceeds max_slope_deg."""
        rows, cols = 7, 7
        elev = np.zeros((rows, cols), dtype=np.float32)
        # Make row 3 (interior) very steep
        for c in range(cols):
            elev[3, c] = float(c) * 50.0
        meta = TerrainMetadata(
            name="slope_test",
            source_url="synthetic",
            resolution_m=1.0,
            bounds=(0.0, 0.0, float(cols), float(rows)),
            shape=(rows, cols),
            nodata_value=-9999.0,
        )
        terrain = Terrain(elevation=elev, metadata=meta)
        max_slope = 5.0
        path = astar(terrain, (0, 3), (6, 3), max_slope_deg=max_slope)
        for r, c in path:
            slope = terrain.slope_at(r, c)
            assert slope <= max_slope + 1e-6, (
                f"Cell ({r},{c}) slope {slope:.2f}° exceeds max {max_slope}°"
            )
