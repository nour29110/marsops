"""Terrain data loading and representation for Mars elevation models.

Provides the :class:`Terrain` wrapper around a 2-D NumPy elevation grid,
the :class:`TerrainMetadata` Pydantic model, and a loader function that
produces a Jezero-Crater-like DEM (synthetic, seeded for reproducibility).
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import rasterio
from pydantic import BaseModel
from rasterio.transform import from_bounds

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TerrainMetadata(BaseModel):
    """Metadata describing a terrain elevation grid.

    Attributes:
        name: Human-readable name for this terrain dataset.
        source_url: URL or path the data was obtained from.
        resolution_m: Ground-sample distance in metres per pixel.
        bounds: Geographic extent as (min_lon, min_lat, max_lon, max_lat).
        shape: Grid dimensions as (rows, cols).
        nodata_value: Sentinel value used for missing data cells.
    """

    name: str
    source_url: str
    resolution_m: float
    bounds: tuple[float, float, float, float]
    shape: tuple[int, int]
    nodata_value: float


# ---------------------------------------------------------------------------
# Terrain class
# ---------------------------------------------------------------------------


class Terrain:
    """2-D elevation grid with metadata and query helpers.

    Args:
        elevation: 2-D float NumPy array of elevation values.
        metadata: Accompanying :class:`TerrainMetadata`.

    Raises:
        ValueError: If *elevation* is not 2-D, not a float dtype, or if its
            shape does not match ``metadata.shape``.
    """

    def __init__(self, elevation: np.ndarray, metadata: TerrainMetadata) -> None:
        if elevation.ndim != 2:
            msg = f"elevation must be 2-D, got {elevation.ndim}-D"
            raise ValueError(msg)
        if not np.issubdtype(elevation.dtype, np.floating):
            msg = f"elevation must be a float dtype, got {elevation.dtype}"
            raise ValueError(msg)
        if elevation.shape != metadata.shape:
            msg = (
                f"elevation shape {elevation.shape} does not match metadata shape {metadata.shape}"
            )
            raise ValueError(msg)
        self._elevation = elevation
        self._metadata = metadata

    # -- properties ---------------------------------------------------------

    @property
    def elevation(self) -> np.ndarray:
        """Raw elevation array."""
        return self._elevation

    @property
    def metadata(self) -> TerrainMetadata:
        """Terrain metadata."""
        return self._metadata

    @property
    def shape(self) -> tuple[int, int]:
        """Grid dimensions as (rows, cols)."""
        rows, cols = self._elevation.shape
        return (int(rows), int(cols))

    @property
    def min_elevation(self) -> float:
        """Minimum elevation ignoring nodata cells."""
        mask = ~np.isclose(self._elevation, self._metadata.nodata_value, atol=1e-6)
        if not np.any(mask):
            return float(self._metadata.nodata_value)
        return float(np.min(self._elevation[mask]))

    @property
    def max_elevation(self) -> float:
        """Maximum elevation ignoring nodata cells."""
        mask = ~np.isclose(self._elevation, self._metadata.nodata_value, atol=1e-6)
        if not np.any(mask):
            return float(self._metadata.nodata_value)
        return float(np.max(self._elevation[mask]))

    # -- internal helpers ---------------------------------------------------

    def _is_nodata(self, row: int, col: int) -> bool:
        """Return True if the cell at (row, col) is the nodata sentinel."""
        return bool(
            np.isclose(
                self._elevation[row, col],
                self._metadata.nodata_value,
                atol=1e-6,
            )
        )

    # -- cell queries -------------------------------------------------------

    def elevation_at(self, row: int, col: int) -> float:
        """Return the elevation at grid position (*row*, *col*).

        Args:
            row: Row index (0-based).
            col: Column index (0-based).

        Returns:
            Elevation value as a Python float.

        Raises:
            IndexError: If *row* or *col* is out of bounds.
        """
        rows, cols = self.shape
        if row < 0 or row >= rows or col < 0 or col >= cols:
            msg = f"({row}, {col}) is out of bounds for shape {self.shape}"
            raise IndexError(msg)
        return float(self._elevation[row, col])

    def slope_at(self, row: int, col: int) -> float:
        """Compute local slope in degrees at (*row*, *col*).

        Uses a 3x3 neighbourhood gradient.  Edge cells (where the full 3x3
        window is unavailable) return ``0.0``.

        Args:
            row: Row index.
            col: Column index.

        Returns:
            Slope in degrees.
        """
        rows, cols = self.shape
        if row <= 0 or row >= rows - 1 or col <= 0 or col >= cols - 1:
            return 0.0
        window = self._elevation[row - 1 : row + 2, col - 1 : col + 2]
        gy, gx = np.gradient(window, self._metadata.resolution_m)
        slope_rad = np.arctan(np.sqrt(gx[1, 1] ** 2 + gy[1, 1] ** 2))
        return float(np.degrees(slope_rad))

    def is_traversable(self, row: int, col: int, max_slope_deg: float = 25.0) -> bool:
        """Determine whether the cell at (*row*, *col*) is traversable.

        A cell is non-traversable if it is out of bounds, contains the nodata
        sentinel, or if its local slope exceeds *max_slope_deg*.  The default
        of 25 degrees roughly corresponds to the operational slope limit of the
        Curiosity rover (JPL Mars Science Laboratory mobility constraints).

        Args:
            row: Row index.
            col: Column index.
            max_slope_deg: Maximum allowable slope in degrees.

        Returns:
            ``True`` if the cell can be driven over; ``False`` for out-of-bounds
            cells.
        """
        rows, cols = self.shape
        if row < 0 or row >= rows or col < 0 or col >= cols:
            return False
        if self._is_nodata(row, col):
            return False
        return self.slope_at(row, col) <= max_slope_deg

    # -- transforms ---------------------------------------------------------

    def to_downsampled(self, factor: int) -> Terrain:
        """Return a new :class:`Terrain` keeping every *factor*-th pixel.

        Args:
            factor: Downsample factor (must be >= 1).

        Returns:
            A new, smaller :class:`Terrain` with updated metadata.

        Raises:
            ValueError: If *factor* < 1.
        """
        if factor < 1:
            msg = f"factor must be >= 1, got {factor}"
            raise ValueError(msg)
        downsampled = self._elevation[::factor, ::factor]
        new_shape = (int(downsampled.shape[0]), int(downsampled.shape[1]))
        new_meta = self._metadata.model_copy(
            update={
                "resolution_m": self._metadata.resolution_m * factor,
                "shape": new_shape,
            }
        )
        return Terrain(elevation=downsampled.copy(), metadata=new_meta)


# ---------------------------------------------------------------------------
# Synthetic DEM generator
# ---------------------------------------------------------------------------


def _generate_synthetic_jezero(rows: int = 500, cols: int = 500) -> np.ndarray:
    """Generate a synthetic Jezero-like crater DEM.

    Produces a 2-D float32 array with layered sinusoidal noise and a
    crater-shaped depression in the centre.  Fully deterministic (seed 42).

    Args:
        rows: Number of pixel rows.
        cols: Number of pixel columns.

    Returns:
        A ``(rows, cols)`` float32 NumPy array of synthetic elevations in
        metres relative to the Mars areoid.
    """
    rng = np.random.default_rng(42)

    # Base elevation around -2500 m (typical Jezero floor)
    y = np.linspace(0, 1, rows, dtype=np.float32)
    x = np.linspace(0, 1, cols, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)

    # Layered pseudo-noise (sum of sinusoids at different frequencies)
    elevation = np.zeros((rows, cols), dtype=np.float32)
    for freq in (2, 5, 11, 23):
        phase_x = rng.uniform(0, 2 * np.pi)
        phase_y = rng.uniform(0, 2 * np.pi)
        amplitude = 80.0 / freq
        elevation += (
            amplitude
            * np.sin(2 * np.pi * freq * xx + phase_x)
            * np.cos(2 * np.pi * freq * yy + phase_y)
        ).astype(np.float32)

    # Crater bowl: radial Gaussian depression centred at (0.5, 0.5)
    cx, cy = 0.5, 0.5
    r2 = (xx - cx) ** 2 + (yy - cy) ** 2
    crater_depth = 400.0  # metres
    crater_radius = 0.3
    bowl = -crater_depth * np.exp(-r2 / (2 * crater_radius**2))
    elevation += bowl.astype(np.float32)

    # Shift to realistic Mars elevation range
    elevation += np.float32(-2500.0)

    return elevation


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_JEZERO_BOUNDS = (77.3, 18.1, 77.8, 18.6)  # lon/lat extent (approximate)


def load_jezero_dem(data_dir: Path) -> Terrain:
    """Load (or generate) a Jezero Crater DEM and return a :class:`Terrain`.

    Looks for a cached GeoTIFF at ``data_dir / "raw" / "jezero_synthetic.tif"``.
    If the file does not exist it is generated from deterministic synthetic
    noise (seeded with 42) and saved for reuse.

    Note:
        A real HRSC or CTX DEM could be substituted by placing a GeoTIFF at
        ``data_dir / "raw" / "jezero_hrsc.tif"``.  The loader will prefer it
        when present.

    Args:
        data_dir: Root data directory (typically the repo's ``data/`` folder).

    Returns:
        A :class:`Terrain` instance ready for path planning.
    """
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    real_path = raw_dir / "jezero_hrsc.tif"
    synth_path = raw_dir / "jezero_synthetic.tif"

    if real_path.exists():
        tif_path = real_path
        source = str(real_path)
    elif synth_path.exists():
        tif_path = synth_path
        source = "synthetic (cached)"
    else:
        logger.info("No cached DEM found — generating synthetic Jezero terrain")
        elevation = _generate_synthetic_jezero()
        _write_geotiff(synth_path, elevation, _JEZERO_BOUNDS)
        tif_path = synth_path
        source = "synthetic (generated)"

    return _read_terrain(tif_path, source, name="Jezero Crater DEM")


def _write_geotiff(
    path: Path,
    elevation: np.ndarray,
    bounds: tuple[float, float, float, float],
) -> None:
    """Write a 2-D elevation array as a single-band GeoTIFF.

    Args:
        path: Destination file path.
        elevation: 2-D float32 array.
        bounds: (min_lon, min_lat, max_lon, max_lat).
    """
    rows, cols = elevation.shape
    transform = from_bounds(*bounds, cols, rows)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=rows,
        width=cols,
        count=1,
        dtype=elevation.dtype,
        crs="EPSG:4326",
        transform=transform,
        nodata=-9999.0,
    ) as dst:
        dst.write(elevation, 1)
    logger.info("Wrote synthetic DEM to %s (%d x %d)", path, rows, cols)


def _read_terrain(tif_path: Path, source: str, name: str = "Terrain") -> Terrain:
    """Read a GeoTIFF and return a :class:`Terrain`.

    Args:
        tif_path: Path to the GeoTIFF.
        source: Human-readable source description for metadata.
        name: Human-readable name for the terrain dataset.

    Returns:
        Populated :class:`Terrain`.
    """
    with rasterio.open(tif_path) as src:
        elevation = src.read(1).astype(np.float32)
        bounds_obj = src.bounds
        nodata = float(src.nodata) if src.nodata is not None else -9999.0
        res_x = src.res[0]

    rows, cols = elevation.shape
    bounds = (
        float(bounds_obj.left),
        float(bounds_obj.bottom),
        float(bounds_obj.right),
        float(bounds_obj.top),
    )

    meta = TerrainMetadata(
        name=name,
        source_url=source,
        resolution_m=float(res_x),
        bounds=bounds,
        shape=(rows, cols),
        nodata_value=nodata,
    )

    terrain = Terrain(elevation=elevation, metadata=meta)
    logger.info(
        "Loaded terrain: %s | shape=%s | elev=[%.1f, %.1f] m | res=%.4f m/px",
        meta.name,
        terrain.shape,
        terrain.min_elevation,
        terrain.max_elevation,
        meta.resolution_m,
    )
    return terrain


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _cli() -> None:
    """Load Jezero DEM and log a summary."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    data_dir = Path(__file__).resolve().parents[3] / "data"
    terrain = load_jezero_dem(data_dir)
    logger.info(
        "Summary — %s: %d x %d, elev range [%.1f, %.1f] m",
        terrain.metadata.name,
        terrain.shape[0],
        terrain.shape[1],
        terrain.min_elevation,
        terrain.max_elevation,
    )


if __name__ == "__main__":
    _cli()
