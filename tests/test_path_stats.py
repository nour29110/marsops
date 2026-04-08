"""Tests for src/marsops/planner/path_stats.py."""

from __future__ import annotations

import math

import numpy as np
import pytest

from marsops.planner.path_stats import compute_path_cost, path_elevation_range
from marsops.terrain.loader import Terrain, TerrainMetadata

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_flat_terrain(rows: int, cols: int, base_elev: float = 0.0) -> Terrain:
    """Return a small flat Terrain for testing."""
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


def _constant_cost(terrain: Terrain, row: int, col: int) -> float:
    return 1.0


# ---------------------------------------------------------------------------
# compute_path_cost tests
# ---------------------------------------------------------------------------


class TestComputePathCost:
    """Tests for compute_path_cost."""

    def test_single_cell_path_costs_zero(self) -> None:
        """A one-element path has no moves — cost must be 0.0."""
        terrain = make_flat_terrain(5, 5)
        assert compute_path_cost(terrain, [(2, 2)], _constant_cost) == pytest.approx(0.0)

    def test_cardinal_move_costs_one(self) -> None:
        """One cardinal step with cost_fn=1.0 must yield total cost 1.0."""
        terrain = make_flat_terrain(5, 5)
        cost = compute_path_cost(terrain, [(0, 0), (0, 1)], _constant_cost)
        assert cost == pytest.approx(1.0)

    def test_diagonal_move_costs_sqrt2(self) -> None:
        """One diagonal step with cost_fn=1.0 must yield total cost sqrt(2)."""
        terrain = make_flat_terrain(5, 5)
        cost = compute_path_cost(terrain, [(0, 0), (1, 1)], _constant_cost)
        assert cost == pytest.approx(math.sqrt(2))

    def test_multi_step_path(self) -> None:
        """Three cardinal steps with cost_fn=1.0 must yield cost 3.0."""
        terrain = make_flat_terrain(5, 5)
        path = [(0, 0), (0, 1), (0, 2), (0, 3)]
        cost = compute_path_cost(terrain, path, _constant_cost)
        assert cost == pytest.approx(3.0)

    def test_cost_fn_is_used(self) -> None:
        """compute_path_cost must delegate to the provided cost_fn."""
        terrain = make_flat_terrain(5, 5)

        def double_cost(t: Terrain, r: int, c: int) -> float:
            return 2.0

        cost = compute_path_cost(terrain, [(0, 0), (0, 1)], double_cost)
        assert cost == pytest.approx(2.0)  # 1.0 (cardinal) * 2.0 (cell cost)


# ---------------------------------------------------------------------------
# path_elevation_range tests
# ---------------------------------------------------------------------------


class TestPathElevationRange:
    """Tests for path_elevation_range."""

    def test_single_cell(self) -> None:
        """A one-cell path must return the same value for min and max."""
        terrain = make_flat_terrain(5, 5, base_elev=100.0)
        lo, hi = path_elevation_range(terrain, [(2, 2)])
        assert lo == pytest.approx(100.0)
        assert hi == pytest.approx(100.0)

    def test_flat_terrain_range_is_zero(self) -> None:
        """On a flat terrain min_elev == max_elev for any path."""
        terrain = make_flat_terrain(5, 5, base_elev=42.0)
        lo, hi = path_elevation_range(terrain, [(0, 0), (2, 2), (4, 4)])
        assert lo == pytest.approx(hi)

    def test_varying_elevations(self) -> None:
        """min and max must reflect the actual elevation spread along the path."""
        rows, cols = 1, 5
        elev = np.array([[0.0, 10.0, 5.0, 20.0, 3.0]], dtype=np.float32)
        meta = TerrainMetadata(
            name="ramp",
            source_url="synthetic",
            resolution_m=1.0,
            bounds=(0.0, 0.0, float(cols), float(rows)),
            shape=(rows, cols),
            nodata_value=-9999.0,
        )
        terrain = Terrain(elevation=elev, metadata=meta)
        path = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)]
        lo, hi = path_elevation_range(terrain, path)
        assert lo == pytest.approx(0.0)
        assert hi == pytest.approx(20.0)

    def test_empty_path_raises(self) -> None:
        """An empty path must raise ValueError."""
        terrain = make_flat_terrain(5, 5)
        with pytest.raises(ValueError, match="empty"):
            path_elevation_range(terrain, [])
