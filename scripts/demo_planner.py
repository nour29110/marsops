"""Demo: Opus-powered mission planner on the Jezero Crater terrain.

Loads the synthetic Jezero DEM (5x downsampled), defines a natural-language
mission goal, invokes the mission-planner runtime, prints the plan summary,
and (if feasible) executes it through the rover simulator to generate a
Markdown mission report and animated HTML playback.

Usage::

    uv run python scripts/demo_planner.py
"""

from __future__ import annotations

import logging
from pathlib import Path

from marsops.planner.mission import MissionConstraints, MissionGoal
from marsops.planner.mission_planner_runtime import plan_mission
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


def main() -> None:
    """Load terrain, plan mission, execute it, and write outputs."""
    # -- Load terrain -----------------------------------------------------------
    data_dir = Path(__file__).resolve().parents[1] / "data"
    logger.info("Loading synthetic Jezero DEM (5x downsample) ...")
    terrain = load_jezero_dem(data_dir).to_downsampled(5)
    logger.info(
        "Terrain shape: %s, elev=[%.1f, %.1f] m",
        terrain.shape,
        terrain.min_elevation,
        terrain.max_elevation,
    )

    # -- Define mission goal ----------------------------------------------------
    goal = MissionGoal(
        description="Survey three flat sites in the northwest quadrant and return to base",
        start=(10, 10),
        region_of_interest=(0, 0, 50, 50),
        min_waypoints=3,
        constraints=MissionConstraints(
            must_return_to_start=True,
            min_battery_pct=15.0,
        ),
    )
    logger.info("Mission goal: %s", goal.description)

    # -- Plan mission (mission-planner runtime) ----------------------------------
    logger.info("Running mission planner ...")
    plan = plan_mission(terrain, goal)
    logger.info("\n%s", plan.summary())

    if not plan.feasible:
        logger.warning("Mission plan is INFEASIBLE — skipping execution.")
        return

    # -- Execute the plan -------------------------------------------------------
    rover_config = RoverConfig()
    rover = Rover(terrain=terrain, start=plan.goal.start, config=rover_config)
    waypoints_set = set(plan.waypoints)

    logger.info(
        "Executing plan: %d path cells, %d waypoints ...",
        plan.predicted_distance_cells,
        len(plan.waypoints),
    )
    log = execute_path(rover, plan.full_path, waypoints=waypoints_set)

    logger.info(
        "Execution complete: outcome cells=%d, duration=%.1f s, battery=%.1f%%",
        log.distance_cells(),
        log.duration_s(),
        log.final_battery(),
    )

    # -- Write outputs ----------------------------------------------------------
    output_dir = Path(__file__).resolve().parents[1] / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    report_path = output_dir / "planned_mission_report.md"
    playback_path = output_dir / "planned_mission_playback.html"

    generate_mission_report(log, terrain.metadata.name, report_path)
    logger.info("Mission report written to %s", report_path)

    plot_mission_playback(terrain, log, playback_path, title="MarsOps Planned Mission Playback")
    logger.info("Mission playback written to %s", playback_path)


if __name__ == "__main__":
    main()
