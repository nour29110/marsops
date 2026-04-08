"""Terrain data loading and representation for Mars elevation models.

Provides the :class:`Terrain` wrapper around a 2-D NumPy elevation grid,
the :class:`TerrainMetadata` Pydantic model, and a loader function that
produces a Jezero-Crater-like DEM (synthetic, seeded for reproducibility),
or downloads the real USGS CTX DEM when ``source="real"`` is requested.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Final, Literal

import httpx
import numpy as np
import rasterio
from pydantic import BaseModel
from rasterio.transform import from_bounds

logger = logging.getLogger(__name__)

# Mars mean equatorial radius → metres per degree of arc
_MARS_METERS_PER_DEGREE: Final[float] = math.pi * 3_389_500.0 / 180.0  # ≈ 59 274 m/°

# Direct download URL for the USGS Astrogeology Mars 2020 CTX DTM mosaic
# (9.3 MB GeoTIFF, no authentication required — verified 2026-04-07)
_REAL_DEM_URL: Final[str] = (
    "https://planetarymaps.usgs.gov/mosaic/mars2020_trn/CTX/"
    "JEZ_ctx_B_soc_008_DTM_MOLAtopography_DeltaGeoid_20m_Eqc_latTs0_lon0.tif"
)


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

    Produces a 2-D float32 array with rolling-hill sinusoidal terrain, a
    shallow central crater depression, and a delta-like ramp in the NW
    quadrant.  Fully deterministic (seed 42).

    The terrain is calibrated so that, after 5x downsampling, at least 85 %
    of interior cells are traversable at the default 25° slope limit.

    Design:
        - Base elevation: -2600 m (Jezero crater floor).
        - Large-scale: 2-D sinusoid, amplitude 40 m, wavelength ~150 cells.
        - Medium-scale: 2-D sinusoid, amplitude 15 m, wavelength ~40 cells,
          rotated 30° to break grid alignment.
        - Small noise: ``default_rng(42).normal(0, 3, shape)``.
        - Crater depression: Gaussian centred on the grid, amplitude 60 m,
          sigma = 100 cells.
        - NW delta ramp: bilinear 30 m gradient over the NW quadrant.

    Args:
        rows: Number of pixel rows.
        cols: Number of pixel columns.

    Returns:
        A ``(rows, cols)`` float32 NumPy array of synthetic elevations in
        metres relative to the Mars areoid.
    """
    rng = np.random.default_rng(42)

    # Integer cell-index coordinate grids (float64 for precision during build)
    row_idx = np.arange(rows, dtype=np.float64)
    col_idx = np.arange(cols, dtype=np.float64)
    cc, rr = np.meshgrid(col_idx, row_idx)

    # -- Large-scale rolling hills: amplitude 40 m, wavelength ~150 cells ----
    phase_lr = float(rng.uniform(0.0, 2.0 * np.pi))
    phase_lc = float(rng.uniform(0.0, 2.0 * np.pi))
    large_scale: np.ndarray = (
        40.0
        * np.sin(2.0 * np.pi * rr / 150.0 + phase_lr)
        * np.cos(2.0 * np.pi * cc / 150.0 + phase_lc)
    )

    # -- Medium-scale: amplitude 15 m, wavelength ~40 cells, rotated 30° -----
    theta = np.radians(30.0)
    rr_rot: np.ndarray = rr * np.cos(theta) + cc * np.sin(theta)
    cc_rot: np.ndarray = -rr * np.sin(theta) + cc * np.cos(theta)
    phase_mr = float(rng.uniform(0.0, 2.0 * np.pi))
    phase_mc = float(rng.uniform(0.0, 2.0 * np.pi))
    medium_scale: np.ndarray = (
        15.0
        * np.sin(2.0 * np.pi * rr_rot / 40.0 + phase_mr)
        * np.cos(2.0 * np.pi * cc_rot / 40.0 + phase_mc)
    )

    # -- Small-scale noise: std = 3 m (seeded rng) ---------------------------
    noise: np.ndarray = rng.normal(0.0, 3.0, (rows, cols))

    # -- Shallow crater: Gaussian depression, amplitude 60 m, sigma = 100 cells --
    cr: float = rows / 2.0
    cc_ctr: float = cols / 2.0
    r2: np.ndarray = (rr - cr) ** 2 + (cc - cc_ctr) ** 2
    crater: np.ndarray = -60.0 * np.exp(-r2 / (2.0 * 100.0**2))

    # -- NW delta ramp: bilinear 30 m gradient across the NW quadrant --------
    # Evokes Jezero's river delta incised from the northwest.
    ramp_r: np.ndarray = np.maximum(0.0, 1.0 - 2.0 * rr / rows)
    ramp_c: np.ndarray = np.maximum(0.0, 1.0 - 2.0 * cc / cols)
    ramp: np.ndarray = 30.0 * ramp_r * ramp_c

    # -- Combine and shift to Jezero floor elevation -------------------------
    elevation: np.ndarray = large_scale + medium_scale + noise + crater + ramp - 2600.0

    return elevation.astype(np.float32)


# ---------------------------------------------------------------------------
# Loader helpers
# ---------------------------------------------------------------------------

_JEZERO_BOUNDS = (77.3, 18.1, 77.8, 18.6)  # lon/lat extent (approximate)


def _download_real_dem(dest: Path) -> None:
    """Download the USGS Astrogeology CTX DTM mosaic (~9 MB) to *dest*.

    Args:
        dest: Local path to write the GeoTIFF.

    Raises:
        RuntimeError: If the HTTP request fails or the file cannot be written.
            Includes instructions for manual placement.
    """
    logger.info("Downloading real Jezero DEM (~9 MB) from USGS Astrogeology …")
    try:
        with httpx.stream("GET", _REAL_DEM_URL, follow_redirects=True, timeout=120.0) as resp:
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=65_536):
                    fh.write(chunk)
    except httpx.HTTPError as exc:
        msg = (
            f"Failed to download real Jezero DEM: {exc!s}\n"
            "Manually place a GeoTIFF at data/raw/jezero_real.tif "
            "and re-run with source='real'."
        )
        raise RuntimeError(msg) from exc
    logger.info("Saved real Jezero DEM to %s", dest)


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

    For geographic CRS (EPSG:4326) the pixel size is converted from degrees
    to metres using the Mars mean radius.  For projected CRS the pixel size
    is used directly.

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

        if src.crs is not None and src.crs.is_geographic:
            mean_lat_rad = math.radians((float(bounds_obj.bottom) + float(bounds_obj.top)) / 2.0)
            res_lon_m = float(src.res[0]) * _MARS_METERS_PER_DEGREE * math.cos(mean_lat_rad)
            res_lat_m = float(src.res[1]) * _MARS_METERS_PER_DEGREE
            resolution_m = (res_lon_m + res_lat_m) / 2.0
        else:
            resolution_m = float(src.res[0])

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
        resolution_m=resolution_m,
        bounds=bounds,
        shape=(rows, cols),
        nodata_value=nodata,
    )

    terrain = Terrain(elevation=elevation, metadata=meta)
    logger.info(
        "Loaded terrain: %s | shape=%s | elev=[%.1f, %.1f] m | res=%.1f m/px",
        meta.name,
        terrain.shape,
        terrain.min_elevation,
        terrain.max_elevation,
        meta.resolution_m,
    )
    return terrain


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_jezero_dem(
    data_dir: Path,
    *,
    source: Literal["synthetic", "real"] = "synthetic",
) -> Terrain:
    """Load (or generate) a Jezero Crater DEM and return a :class:`Terrain`.

    When *source* is ``"synthetic"`` (default), looks for a cached GeoTIFF at
    ``data_dir / "raw" / "jezero_synthetic.tif"``.  If missing, a deterministic
    synthetic terrain is generated (seed 42) and saved for reuse.

    When *source* is ``"real"``, looks for ``data_dir / "raw" / "jezero_real.tif"``.
    If missing, attempts to download the USGS Astrogeology Mars 2020 CTX DTM
    (~9 MB, no authentication).  If the download fails, raises :exc:`RuntimeError`
    with placement instructions — does **not** silently fall back to synthetic.

    Args:
        data_dir: Root data directory (typically the repo's ``data/`` folder).
        source: Which DEM to load — ``"synthetic"`` (default) or ``"real"``.

    Returns:
        A :class:`Terrain` instance ready for path planning.

    Raises:
        RuntimeError: When ``source="real"`` and the DEM cannot be found or
            downloaded.
    """
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    if source == "real":
        real_path = raw_dir / "jezero_real.tif"
        if not real_path.exists():
            _download_real_dem(real_path)
        return _read_terrain(real_path, str(real_path), name="Jezero Crater DEM (Real CTX)")

    # source == "synthetic"
    synth_path = raw_dir / "jezero_synthetic.tif"
    if synth_path.exists():
        tif_source = "synthetic (cached)"
    else:
        logger.info("No cached DEM found — generating synthetic Jezero terrain")
        elevation = _generate_synthetic_jezero()
        _write_geotiff(synth_path, elevation, _JEZERO_BOUNDS)
        tif_source = "synthetic (generated)"

    return _read_terrain(synth_path, tif_source, name="Jezero Crater DEM")


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
