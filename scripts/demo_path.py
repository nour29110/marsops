"""Demo: A* path planning on the Jezero Crater terrain.

Loads (or generates) the synthetic Jezero DEM, downsamples it to 100x100,
plans a rover path across the crater rim using the default slope-cost
function, and renders an interactive HTML visualisation.

Usage::

    uv run python scripts/demo_path.py
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

from marsops.planner import astar, compute_path_cost, path_elevation_range, terrain_cost
from marsops.terrain.loader import load_jezero_dem
from marsops.viz.path_plot import plot_terrain_with_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
_DATA_DIR: Final[Path] = _REPO_ROOT / "data"
_OUTPUT_DIR: Final[Path] = _REPO_ROOT / "output"


def main() -> None:
    """Run the Jezero path-planning demo."""
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # -- Load and downsample -------------------------------------------------
    logger.info("Loading Jezero DEM from %s", _DATA_DIR)
    terrain_full = load_jezero_dem(_DATA_DIR)
    logger.info("Full terrain shape: %s", terrain_full.shape)

    terrain = terrain_full.to_downsampled(5)
    logger.info("Downsampled terrain shape: %s", terrain.shape)

    # -- Plan path -----------------------------------------------------------
    # NOTE: The synthetic Jezero DEM is a crater bowl; after downsampling by 5x
    # the interior cells have ~90° slopes and are non-traversable at the default
    # 25° limit.  Traversable cells are concentrated on the crater rim (edges).
    # We use (0, 0) -> (61, 99) — opposite corners of the rim — as the demo pair.
    start: tuple[int, int] = (0, 0)
    goal: tuple[int, int] = (61, 99)
    logger.info("Planning path from %s to %s", start, goal)

    path = astar(terrain, start=start, goal=goal)

    # -- Compute path statistics (via testable module functions) -------------
    min_elev, max_elev = path_elevation_range(terrain, path)
    total_cost = compute_path_cost(terrain, path, terrain_cost)

    logger.info(
        "Path found: %d waypoints | min_elev=%.1f m | max_elev=%.1f m | total_cost=%.2f",
        len(path),
        min_elev,
        max_elev,
        total_cost,
    )

    # -- Render --------------------------------------------------------------
    output_html = _OUTPUT_DIR / "jezero_path.html"
    plot_terrain_with_path(
        terrain=terrain,
        path=path,
        output_path=output_html,
        title="Jezero Crater — A* Rover Path (100x100 downsampled)",
    )
    logger.info("Visualisation saved to %s", output_html)


if __name__ == "__main__":
    main()
