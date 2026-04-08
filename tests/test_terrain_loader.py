"""Tests for marsops.terrain.loader module."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from marsops.terrain.loader import (
    Terrain,
    TerrainMetadata,
    _generate_synthetic_jezero,
    load_jezero_dem,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

NODATA = -9999.0


def _make_metadata(
    rows: int = 10,
    cols: int = 10,
    resolution_m: float = 1.0,
    nodata_value: float = NODATA,
) -> TerrainMetadata:
    """Create a minimal TerrainMetadata for testing."""
    return TerrainMetadata(
        name="test",
        source_url="test://",
        resolution_m=resolution_m,
        bounds=(0.0, 0.0, 1.0, 1.0),
        shape=(rows, cols),
        nodata_value=nodata_value,
    )


def _make_terrain(
    rows: int = 10,
    cols: int = 10,
    fill: float = 0.0,
    resolution_m: float = 1.0,
) -> Terrain:
    """Create a flat Terrain of given size filled with *fill*."""
    meta = _make_metadata(rows=rows, cols=cols, resolution_m=resolution_m)
    elev = np.full((rows, cols), fill, dtype=np.float32)
    return Terrain(elevation=elev, metadata=meta)


@pytest.fixture()
def flat_terrain() -> Terrain:
    """10x10 flat terrain at elevation 0."""
    return _make_terrain(10, 10, fill=0.0)


@pytest.fixture()
def tilted_terrain() -> Terrain:
    """10x10 terrain with a linear east-west slope.

    Elevation increases by 1.0 m per column, resolution=1.0 m.
    Expected slope for interior cells: arctan(1) ~ 45 degrees.
    """
    meta = _make_metadata(rows=10, cols=10, resolution_m=1.0)
    elev = np.tile(np.arange(10, dtype=np.float32), (10, 1))
    return Terrain(elevation=elev, metadata=meta)


# ---------------------------------------------------------------------------
# TerrainMetadata validation
# ---------------------------------------------------------------------------


class TestTerrainMetadata:
    """Tests for the TerrainMetadata Pydantic model."""

    def test_valid_construction(self) -> None:
        meta = _make_metadata()
        assert meta.name == "test"
        assert meta.resolution_m == 1.0
        assert meta.shape == (10, 10)
        assert meta.nodata_value == NODATA

    def test_field_types(self) -> None:
        meta = _make_metadata()
        assert isinstance(meta.name, str)
        assert isinstance(meta.resolution_m, float)
        assert isinstance(meta.bounds, tuple)
        assert isinstance(meta.shape, tuple)
        assert len(meta.bounds) == 4
        assert len(meta.shape) == 2

    def test_invalid_missing_field(self) -> None:
        with pytest.raises(Exception):  # noqa: B017 — Pydantic ValidationError
            TerrainMetadata(
                name="test",
                # source_url missing
                resolution_m=1.0,
                bounds=(0.0, 0.0, 1.0, 1.0),
                shape=(10, 10),
                nodata_value=NODATA,
            )  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Terrain constructor validation
# ---------------------------------------------------------------------------


class TestTerrainConstructor:
    """Tests for Terrain.__init__ validation."""

    def test_valid_construction(self) -> None:
        t = _make_terrain(5, 5)
        assert t.shape == (5, 5)
        assert t.metadata.shape == (5, 5)

    def test_shape_mismatch_raises(self) -> None:
        meta = _make_metadata(rows=5, cols=5)
        elev = np.zeros((3, 3), dtype=np.float32)
        with pytest.raises(ValueError, match="does not match metadata shape"):
            Terrain(elevation=elev, metadata=meta)

    def test_1d_array_raises(self) -> None:
        meta = _make_metadata(rows=1, cols=10)
        elev = np.zeros(10, dtype=np.float32)  # 1-D
        with pytest.raises(ValueError, match="must be 2-D"):
            Terrain(elevation=elev, metadata=meta)

    def test_3d_array_raises(self) -> None:
        meta = _make_metadata(rows=5, cols=5)
        elev = np.zeros((5, 5, 1), dtype=np.float32)
        with pytest.raises(ValueError, match="must be 2-D"):
            Terrain(elevation=elev, metadata=meta)

    def test_int_dtype_raises(self) -> None:
        meta = _make_metadata(rows=5, cols=5)
        elev = np.zeros((5, 5), dtype=np.int32)
        with pytest.raises(ValueError, match="must be a float dtype"):
            Terrain(elevation=elev, metadata=meta)

    def test_float64_accepted(self) -> None:
        meta = _make_metadata(rows=5, cols=5)
        elev = np.zeros((5, 5), dtype=np.float64)
        t = Terrain(elevation=elev, metadata=meta)
        assert t.shape == (5, 5)


# ---------------------------------------------------------------------------
# Terrain properties
# ---------------------------------------------------------------------------


class TestTerrainProperties:
    """Tests for computed properties (min/max elevation, shape)."""

    def test_shape_property(self, flat_terrain: Terrain) -> None:
        assert flat_terrain.shape == (10, 10)

    def test_min_max_elevation_flat(self, flat_terrain: Terrain) -> None:
        assert flat_terrain.min_elevation == 0.0
        assert flat_terrain.max_elevation == 0.0

    def test_min_max_elevation_varied(self) -> None:
        meta = _make_metadata(rows=3, cols=3)
        elev = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]], dtype=np.float32)
        t = Terrain(elevation=elev, metadata=meta)
        assert t.min_elevation == 1.0
        assert t.max_elevation == 9.0

    def test_min_max_ignores_nodata(self) -> None:
        meta = _make_metadata(rows=3, cols=3, nodata_value=NODATA)
        elev = np.array(
            [[NODATA, 2.0, 3.0], [4.0, NODATA, 6.0], [7.0, 8.0, NODATA]],
            dtype=np.float32,
        )
        t = Terrain(elevation=elev, metadata=meta)
        assert t.min_elevation == 2.0
        assert t.max_elevation == 8.0

    def test_all_nodata_returns_nodata(self) -> None:
        meta = _make_metadata(rows=2, cols=2, nodata_value=NODATA)
        elev = np.full((2, 2), NODATA, dtype=np.float32)
        t = Terrain(elevation=elev, metadata=meta)
        assert t.min_elevation == NODATA
        assert t.max_elevation == NODATA


# ---------------------------------------------------------------------------
# elevation_at
# ---------------------------------------------------------------------------


class TestElevationAt:
    """Tests for Terrain.elevation_at including Hypothesis bounds checking."""

    def test_valid_index(self, flat_terrain: Terrain) -> None:
        assert flat_terrain.elevation_at(0, 0) == 0.0
        assert flat_terrain.elevation_at(9, 9) == 0.0

    def test_known_values(self) -> None:
        meta = _make_metadata(rows=3, cols=3)
        elev = np.arange(9, dtype=np.float32).reshape(3, 3)
        t = Terrain(elevation=elev, metadata=meta)
        assert t.elevation_at(0, 0) == 0.0
        assert t.elevation_at(1, 2) == 5.0
        assert t.elevation_at(2, 2) == 8.0

    @pytest.mark.parametrize(
        ("row", "col"),
        [(-1, 0), (0, -1), (10, 0), (0, 10), (10, 10), (-1, -1)],
    )
    def test_out_of_bounds(self, flat_terrain: Terrain, row: int, col: int) -> None:
        with pytest.raises(IndexError, match="out of bounds"):
            flat_terrain.elevation_at(row, col)

    @given(
        row=st.integers(min_value=0, max_value=9),
        col=st.integers(min_value=0, max_value=9),
    )
    @settings(max_examples=50)
    def test_valid_indices_hypothesis(self, row: int, col: int) -> None:
        t = _make_terrain(10, 10, fill=42.0)
        assert t.elevation_at(row, col) == 42.0

    @given(
        row=st.integers(min_value=10, max_value=1000),
        col=st.integers(min_value=10, max_value=1000),
    )
    @settings(max_examples=50)
    def test_invalid_indices_hypothesis(self, row: int, col: int) -> None:
        t = _make_terrain(10, 10, fill=0.0)
        with pytest.raises(IndexError):
            t.elevation_at(row, col)

    @given(
        row=st.integers(max_value=-1),
        col=st.integers(min_value=0, max_value=9),
    )
    @settings(max_examples=30)
    def test_negative_row_hypothesis(self, row: int, col: int) -> None:
        t = _make_terrain(10, 10, fill=0.0)
        with pytest.raises(IndexError):
            t.elevation_at(row, col)


# ---------------------------------------------------------------------------
# slope_at
# ---------------------------------------------------------------------------


class TestSlopeAt:
    """Tests for Terrain.slope_at."""

    @pytest.mark.parametrize(
        ("row", "col"),
        [(0, 0), (0, 5), (5, 0), (9, 5), (5, 9), (0, 9), (9, 0), (9, 9)],
    )
    def test_edge_cells_return_zero(self, flat_terrain: Terrain, row: int, col: int) -> None:
        assert flat_terrain.slope_at(row, col) == 0.0

    def test_flat_interior_near_zero(self, flat_terrain: Terrain) -> None:
        slope = flat_terrain.slope_at(5, 5)
        assert slope == pytest.approx(0.0, abs=1e-6)

    def test_tilted_interior_nonzero(self, tilted_terrain: Terrain) -> None:
        slope = tilted_terrain.slope_at(5, 5)
        # East-west gradient of 1.0 m/m at resolution 1.0 => arctan(1) ~ 45 degrees
        assert slope == pytest.approx(45.0, abs=0.5)

    def test_tilted_edge_returns_zero(self, tilted_terrain: Terrain) -> None:
        assert tilted_terrain.slope_at(0, 0) == 0.0
        assert tilted_terrain.slope_at(9, 9) == 0.0


# ---------------------------------------------------------------------------
# is_traversable
# ---------------------------------------------------------------------------


class TestIsTraversable:
    """Tests for Terrain.is_traversable."""

    def test_nodata_cell_not_traversable(self) -> None:
        meta = _make_metadata(rows=5, cols=5)
        elev = np.zeros((5, 5), dtype=np.float32)
        elev[2, 2] = NODATA
        t = Terrain(elevation=elev, metadata=meta)
        assert t.is_traversable(2, 2) is False

    def test_flat_cell_traversable(self, flat_terrain: Terrain) -> None:
        assert flat_terrain.is_traversable(5, 5) is True

    def test_steep_cell_not_traversable(self, tilted_terrain: Terrain) -> None:
        # Interior slope ~45 deg exceeds default 25 deg limit
        assert tilted_terrain.is_traversable(5, 5) is False

    def test_steep_cell_traversable_with_high_limit(self, tilted_terrain: Terrain) -> None:
        assert tilted_terrain.is_traversable(5, 5, max_slope_deg=90.0) is True

    def test_edge_cell_traversable(self, tilted_terrain: Terrain) -> None:
        # Edge cells have slope 0.0 from slope_at, so they should be traversable
        # as long as they are not nodata
        assert tilted_terrain.is_traversable(0, 0) is True

    def test_out_of_bounds_not_traversable(self, flat_terrain: Terrain) -> None:
        assert flat_terrain.is_traversable(-1, 0) is False
        assert flat_terrain.is_traversable(0, -1) is False
        assert flat_terrain.is_traversable(10, 0) is False
        assert flat_terrain.is_traversable(0, 10) is False


# ---------------------------------------------------------------------------
# to_downsampled
# ---------------------------------------------------------------------------


class TestToDownsampled:
    """Tests for Terrain.to_downsampled."""

    def test_factor_1_identity(self, flat_terrain: Terrain) -> None:
        ds = flat_terrain.to_downsampled(1)
        assert ds.shape == flat_terrain.shape
        np.testing.assert_array_equal(ds.elevation, flat_terrain.elevation)

    def test_factor_2_halves_shape(self) -> None:
        t = _make_terrain(10, 10, fill=5.0)
        ds = t.to_downsampled(2)
        assert ds.shape == (5, 5)

    def test_metadata_resolution_updated(self) -> None:
        t = _make_terrain(10, 10, fill=0.0, resolution_m=2.0)
        ds = t.to_downsampled(3)
        assert ds.metadata.resolution_m == pytest.approx(6.0)

    def test_metadata_shape_updated(self) -> None:
        t = _make_terrain(10, 10)
        ds = t.to_downsampled(5)
        assert ds.metadata.shape == ds.shape == (2, 2)

    def test_factor_less_than_1_raises(self) -> None:
        t = _make_terrain(10, 10)
        with pytest.raises(ValueError, match="factor must be >= 1"):
            t.to_downsampled(0)

    def test_factor_negative_raises(self) -> None:
        t = _make_terrain(10, 10)
        with pytest.raises(ValueError, match="factor must be >= 1"):
            t.to_downsampled(-3)

    @given(factor=st.integers(min_value=1, max_value=10))
    @settings(max_examples=20)
    def test_downsample_shape_hypothesis(self, factor: int) -> None:
        rows, cols = 50, 50
        t = _make_terrain(rows, cols, fill=0.0, resolution_m=1.0)
        ds = t.to_downsampled(factor)
        expected_rows = len(range(0, rows, factor))
        expected_cols = len(range(0, cols, factor))
        assert ds.shape == (expected_rows, expected_cols)
        assert ds.metadata.resolution_m == pytest.approx(float(factor))

    def test_downsampled_is_independent_copy(self) -> None:
        t = _make_terrain(10, 10, fill=1.0)
        ds = t.to_downsampled(2)
        ds.elevation[0, 0] = 999.0
        assert t.elevation_at(0, 0) == 1.0  # original unmodified


# ---------------------------------------------------------------------------
# _generate_synthetic_jezero
# ---------------------------------------------------------------------------


class TestGenerateSyntheticJezero:
    """Tests for the deterministic synthetic DEM generator."""

    def test_deterministic(self) -> None:
        a = _generate_synthetic_jezero()
        b = _generate_synthetic_jezero()
        np.testing.assert_array_equal(a, b)

    def test_default_shape(self) -> None:
        elev = _generate_synthetic_jezero()
        assert elev.shape == (500, 500)

    def test_custom_shape(self) -> None:
        elev = _generate_synthetic_jezero(rows=100, cols=200)
        assert elev.shape == (100, 200)

    def test_dtype_float32(self) -> None:
        elev = _generate_synthetic_jezero()
        assert elev.dtype == np.float32

    def test_has_crater_depression(self) -> None:
        elev = _generate_synthetic_jezero()
        centre = elev[240:260, 240:260].mean()
        edge = elev[0:20, 0:20].mean()
        # Centre should be lower (crater depression)
        assert centre < edge


# ---------------------------------------------------------------------------
# load_jezero_dem (end-to-end with tmp_path)
# ---------------------------------------------------------------------------


class TestLoadJezeroDem:
    """End-to-end tests for load_jezero_dem using temporary directories."""

    def test_generates_and_loads(self, tmp_path: Path) -> None:
        terrain = load_jezero_dem(tmp_path)
        assert terrain.shape == (500, 500)
        assert terrain.metadata.name == "Jezero Crater DEM"
        assert terrain.metadata.nodata_value == -9999.0
        assert len(terrain.metadata.bounds) == 4

    def test_cached_second_call(self, tmp_path: Path) -> None:
        t1 = load_jezero_dem(tmp_path)
        t2 = load_jezero_dem(tmp_path)
        # Both should produce identical results
        assert t1.shape == t2.shape
        np.testing.assert_array_equal(t1.elevation, t2.elevation)
        # Second call uses "synthetic (cached)" source
        assert "cached" in t2.metadata.source_url

    def test_creates_raw_directory(self, tmp_path: Path) -> None:
        load_jezero_dem(tmp_path)
        assert (tmp_path / "raw").is_dir()
        assert (tmp_path / "raw" / "jezero_synthetic.tif").is_file()

    def test_metadata_bounds_match(self, tmp_path: Path) -> None:
        terrain = load_jezero_dem(tmp_path)
        # Bounds should approximately match the Jezero region
        min_lon, min_lat, max_lon, max_lat = terrain.metadata.bounds
        assert 77.0 < min_lon < 78.0
        assert 18.0 < min_lat < 19.0
        assert 77.0 < max_lon < 78.0
        assert 18.0 < max_lat < 19.0
