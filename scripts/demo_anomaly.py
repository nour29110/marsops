"""Demo: anomaly injection and mid-mission replanning on Jezero terrain.

Loads the synthetic Jezero DEM (5x downsampled), plans a mission, then
executes it with two injected anomalies:

1. ``dust_storm`` at step 4, severity 0.6 -- drains battery and forces idle.
2. ``wheel_stuck`` at step 7, blocking cells around the path midpoint --
   triggers recovery replanning.

Outputs:
    output/anomaly_mission_<timestamp>.md   -- mission report
    output/anomaly_mission_<timestamp>.html -- interactive playback

Usage::

    uv run python scripts/demo_anomaly.py
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from marsops.planner.mission import MissionConstraints, MissionGoal
from marsops.planner.mission_planner_runtime import plan_mission
from marsops.planner.recovery import recover_from_anomaly
from marsops.simulator.anomalies import Anomaly
from marsops.simulator.engine import execute_path_with_recovery
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
    """Load terrain, plan mission, inject anomalies, execute with recovery."""
    # -- Load terrain -----------------------------------------------------------
    data_dir = Path(__file__).resolve().parents[1] / "data"
    logger.info("Loading synthetic Jezero DEM (5x downsample) ...")
    terrain = load_jezero_dem(data_dir).to_downsampled(5)
    logger.info(
        "Terrain shape: %s  elev=[%.1f, %.1f] m  res=%.1f m/px",
        terrain.shape,
        terrain.min_elevation,
        terrain.max_elevation,
        terrain.metadata.resolution_m,
    )

    # -- Define mission goal ----------------------------------------------------
    goal = MissionGoal(
        description="Traverse to (22, 22) via two intermediate waypoints",
        start=(10, 10),
        region_of_interest=(5, 5, 30, 30),
        min_waypoints=2,
        constraints=MissionConstraints(
            min_battery_pct=15.0,
            max_slope_deg=25.0,
            must_return_to_start=False,
        ),
    )
    logger.info("Mission goal: %s", goal.description)

    # -- Plan mission -----------------------------------------------------------
    logger.info("Running mission planner ...")
    rover_config = RoverConfig()
    plan = plan_mission(terrain, goal, rover_config)
    logger.info("\n%s", plan.summary())

    if not plan.feasible:
        logger.error("Planner returned an infeasible plan — cannot run demo.")
        return

    logger.info(
        "Plan feasible: %d waypoints, %d path cells, battery=%.1f%%",
        len(plan.waypoints),
        len(plan.full_path),
        plan.predicted_final_battery_pct,
    )

    # -- Define anomalies -------------------------------------------------------
    anomalies: list[Anomaly] = [
        Anomaly(
            trigger_at_step=4,
            anomaly_type="dust_storm",
            severity=0.6,
            message=(
                "DUST STORM detected at step 4 — visibility < 1 m, solar panels partially obscured."
            ),
        ),
        Anomaly(
            trigger_at_step=7,
            anomaly_type="wheel_stuck",
            severity=0.8,
            message=(
                "WHEEL STUCK at step 7 — right-front wheel jammed on embedded rock. "
                "Cells (16,16), (17,17), (18,18) flagged as blocked."
            ),
            blocked_cells={(16, 16), (17, 17), (18, 18)},
        ),
    ]
    logger.info(
        "Injecting %d anomalies: %s",
        len(anomalies),
        [f"{a.anomaly_type}@step{a.trigger_at_step}" for a in anomalies],
    )

    # -- Execute with recovery --------------------------------------------------
    logger.info("=== MISSION EXECUTION START ===")
    rover = Rover(terrain=terrain, start=goal.start, config=rover_config)

    log = execute_path_with_recovery(
        rover=rover,
        path=plan.full_path,
        waypoints=set(plan.waypoints),
        anomalies=anomalies,
        recovery_fn=recover_from_anomaly,
        terrain=terrain,
        original_goal=goal,
        rover_config=rover_config,
    )

    # -- Summarise outcomes -----------------------------------------------------
    anomaly_events = [e for e in log.events if e.event_type == "anomaly"]
    replan_events = [e for e in log.events if e.event_type == "recovery_replan"]
    final_event = log.events[-1] if log.events else None

    logger.info("=== MISSION EXECUTION END ===")
    logger.info("Total events       : %d", len(log.events))
    logger.info("Anomaly events     : %d", len(anomaly_events))
    logger.info("Recovery replans   : %d", len(replan_events))
    logger.info("Steps taken        : %d", log.distance_cells())
    logger.info("Waypoints reached  : %d", log.waypoints_reached())
    logger.info("Duration           : %.1f s", log.duration_s())
    logger.info("Final battery      : %.1f%%", log.final_battery())
    logger.info(
        "Mission outcome    : %s",
        final_event.event_type if final_event else "unknown",
    )

    for ev in anomaly_events:
        logger.info("  [anomaly] step=%.0fs  %s", ev.timestamp_s, ev.message)
    for ev in replan_events:
        logger.info("  [recovery_replan] step=%.0fs  %s", ev.timestamp_s, ev.message[:120])

    # -- Write outputs ----------------------------------------------------------
    output_dir = Path(__file__).resolve().parents[1] / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"anomaly_mission_{ts}.md"
    html_path = output_dir / f"anomaly_mission_{ts}.html"

    generate_mission_report(log, terrain.metadata.name, report_path)
    plot_mission_playback(terrain, log, html_path, title="MarsOps Anomaly Recovery Demo")

    logger.info("Report  -> %s", report_path)
    logger.info("Playback -> %s", html_path)
    logger.info("Demo complete.")


if __name__ == "__main__":
    main()
