"""Tests for src/marsops/viz/path_plot.py.

Uses small synthetic Terrain instances.  No real DEM is loaded.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from marsops.terrain.loader import Terrain, TerrainMetadata
from marsops.viz.path_plot import plot_terrain_with_path

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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPlotTerrainWithPath:
    """Tests for plot_terrain_with_path."""

    def test_returns_output_path(self, tmp_path: Path) -> None:
        """The function must return the same path it was given."""
        terrain = make_flat_terrain(5, 5)
        out = tmp_path / "test.html"
        result = plot_terrain_with_path(terrain, [(0, 0), (2, 2), (4, 4)], out)
        assert result == out.resolve()

    def test_creates_html_file(self, tmp_path: Path) -> None:
        """An HTML file must exist after the call."""
        terrain = make_flat_terrain(5, 5)
        out = tmp_path / "out.html"
        plot_terrain_with_path(terrain, [(0, 0), (4, 4)], out)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_html_content_contains_title(self, tmp_path: Path) -> None:
        """The generated HTML must embed the custom title string."""
        terrain = make_flat_terrain(5, 5)
        out = tmp_path / "titled.html"
        plot_terrain_with_path(terrain, [(0, 0), (4, 4)], out, title="MyTitle")
        content = out.read_text()
        assert "MyTitle" in content

    def test_empty_path_produces_file(self, tmp_path: Path) -> None:
        """An empty path list must still produce a valid HTML file (heatmap only)."""
        terrain = make_flat_terrain(5, 5)
        out = tmp_path / "empty_path.html"
        result = plot_terrain_with_path(terrain, [], out)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Parent directories must be created automatically if they do not exist."""
        terrain = make_flat_terrain(5, 5)
        nested_out = tmp_path / "a" / "b" / "c" / "plot.html"
        assert not nested_out.parent.exists()
        plot_terrain_with_path(terrain, [(0, 0), (4, 4)], nested_out)
        assert nested_out.exists()

    def test_single_cell_path(self, tmp_path: Path) -> None:
        """A one-cell path (start == goal) must produce a valid file."""
        terrain = make_flat_terrain(5, 5)
        out = tmp_path / "single.html"
        plot_terrain_with_path(terrain, [(2, 2)], out)
        assert out.exists()

    def test_default_title(self, tmp_path: Path) -> None:
        """The default title 'MarsOps Path' must appear in the HTML."""
        terrain = make_flat_terrain(5, 5)
        out = tmp_path / "default_title.html"
        plot_terrain_with_path(terrain, [(0, 0), (4, 4)], out)
        content = out.read_text()
        assert "MarsOps Path" in content

    @pytest.mark.parametrize("elev", [-2500.0, 0.0, 1000.0])
    def test_various_elevation_ranges(self, tmp_path: Path, elev: float) -> None:
        """Elevation values at different ranges must not cause errors."""
        terrain = make_flat_terrain(5, 5, base_elev=elev)
        out = tmp_path / f"elev_{int(elev)}.html"
        plot_terrain_with_path(terrain, [(0, 0), (4, 4)], out)
        assert out.exists()
