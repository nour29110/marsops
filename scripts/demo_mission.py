"""Demo: Full rover mission simulation on the Jezero Crater terrain.

Loads (or generates) the Jezero DEM, downsamples it to ~100x100, plans a
path from (10,10) to (90,90) with intermediate waypoints, runs the rover
simulation, generates a Markdown mission report and an animated HTML playback.

Usage::

    uv run python scripts/demo_mission.py [--source {synthetic,real}]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Final

from marsops.planner.astar import astar
from marsops.simulator.engine import execute_path
from marsops.simulator.rover import Rover, RoverConfig
from marsops.telemetry.reporter import generate_mission_report
from marsops.terrain.loader import load_jezero_dem
from marsops.viz.path_plot import plot_mission_playback

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
_DATA_DIR: Final[Path] = _REPO_ROOT / "data"
_OUTPUT_DIR: Final[Path] = _REPO_ROOT / "output"

_START: Final[tuple[int, int]] = (10, 10)
_GOAL: Final[tuple[int, int]] = (22, 22)
_WAYPOINTS: Final[set[tuple[int, int]]] = {(14, 14), (18, 18)}


def main() -> None:
    """Run the Jezero rover mission demo."""
    parser = argparse.ArgumentParser(description="Jezero rover mission simulation demo")
    parser.add_argument(
        "--source",
        choices=["synthetic", "real"],
        default="synthetic",
        help="DEM source: 'synthetic' (default) or 'real' (USGS CTX download)",
    )
    args = parser.parse_args()

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # -- Load and downsample terrain -----------------------------------------
    logger.info("Loading Jezero DEM (source=%s)", args.source)
    terrain_full = load_jezero_dem(_DATA_DIR, source=args.source)
    terrain = terrain_full.to_downsampled(5)
    logger.info("Terrain shape after 5x downsample: %s", terrain.shape)

    # -- Plan path -----------------------------------------------------------
    logger.info("Planning path %s -> %s with waypoints %s", _START, _GOAL, _WAYPOINTS)
    path = astar(terrain, start=_START, goal=_GOAL)
    logger.info("Path found: %d cells", len(path))

    # -- Simulate mission ----------------------------------------------------
    rover = Rover(terrain=terrain, start=_START, config=RoverConfig())
    log = execute_path(rover, path, waypoints=_WAYPOINTS)
    outcome = (
        "complete" if any(e.event_type == "mission_complete" for e in log.events) else "failed"
    )

    # -- Generate markdown report --------------------------------------------
    report_path = _OUTPUT_DIR / "mission_report.md"
    generate_mission_report(log, terrain_name=terrain.metadata.name, output_path=report_path)

    # -- Generate animated playback ------------------------------------------
    playback_path = _OUTPUT_DIR / "mission_playback.html"
    plot_mission_playback(
        terrain=terrain,
        log=log,
        output_path=playback_path,
        title=f"Jezero Rover Mission Playback (source={args.source})",
    )

    # -- Summary log ---------------------------------------------------------
    logger.info(
        "Mission %s | cells=%d | duration=%.1f s | battery=%.1f%% | "
        "waypoints=%d | report=%s | playback=%s",
        outcome,
        log.distance_cells(),
        log.duration_s(),
        log.final_battery(),
        log.waypoints_reached(),
        report_path,
        playback_path,
    )


if __name__ == "__main__":
    main()
