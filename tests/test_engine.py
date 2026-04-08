"""Tests for marsops.simulator.engine: execute_path."""

from __future__ import annotations

import numpy as np
import pytest

from marsops.simulator.engine import execute_path
from marsops.simulator.rover import Rover, RoverConfig
from marsops.terrain.loader import Terrain, TerrainMetadata

# ---------------------------------------------------------------------------
# Terrain / Rover helpers
# ---------------------------------------------------------------------------

_FLAT_ELEVATION = -2600.0
_NODATA_VALUE = -9999.0


def _make_flat_terrain(rows: int = 10, cols: int = 10) -> Terrain:
    """Return a flat 10x10 terrain with all cells at -2600 m."""
    elevation = np.full((rows, cols), _FLAT_ELEVATION, dtype=np.float32)
    meta = TerrainMetadata(
        name="test",
        source_url="test",
        resolution_m=20.0,
        bounds=(0.0, 0.0, 1.0, 1.0),
        shape=(rows, cols),
        nodata_value=_NODATA_VALUE,
    )
    return Terrain(elevation=elevation, metadata=meta)


def _make_rover(
    start: tuple[int, int] = (0, 0),
    battery_capacity_wh: float = 2000.0,
) -> Rover:
    """Return a Rover on flat terrain with the given start and battery."""
    terrain = _make_flat_terrain()
    config = RoverConfig(battery_capacity_wh=battery_capacity_wh)
    return Rover(terrain=terrain, start=start, config=config)


@pytest.fixture()
def flat_terrain() -> Terrain:
    """10x10 flat terrain at -2600 m."""
    return _make_flat_terrain()


# ---------------------------------------------------------------------------
# Basic 3-cell straight path
# ---------------------------------------------------------------------------


def test_execute_path_event_order_3_cell() -> None:
    """execute_path on a 3-cell path emits: mission_start, step, step, mission_complete."""
    rover = _make_rover(start=(0, 0))
    path: list[tuple[int, int]] = [(0, 0), (0, 1), (0, 2)]
    log = execute_path(rover, path)

    event_types = [e.event_type for e in log.events]
    assert event_types[0] == "mission_start"
    assert event_types[-1] == "mission_complete"
    step_events = [t for t in event_types if t == "step"]
    assert len(step_events) == 2


def test_execute_path_first_event_mission_start() -> None:
    """First event is always mission_start."""
    rover = _make_rover(start=(0, 0))
    log = execute_path(rover, [(0, 0), (0, 1)])
    assert log.events[0].event_type == "mission_start"


def test_execute_path_last_event_mission_complete() -> None:
    """Last event is mission_complete on a successful run."""
    rover = _make_rover(start=(0, 0))
    log = execute_path(rover, [(0, 0), (0, 1), (0, 2)])
    assert log.events[-1].event_type == "mission_complete"


# ---------------------------------------------------------------------------
# Waypoints
# ---------------------------------------------------------------------------


def test_execute_path_waypoint_reached_emitted() -> None:
    """execute_path emits waypoint_reached when rover passes through a waypoint."""
    rover = _make_rover(start=(0, 0))
    path: list[tuple[int, int]] = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4), (0, 5)]
    waypoints: set[tuple[int, int]] = {(0, 3)}
    log = execute_path(rover, path, waypoints=waypoints)

    event_types = [e.event_type for e in log.events]
    assert "waypoint_reached" in event_types


def test_execute_path_waypoint_reached_count() -> None:
    """waypoints_reached equals the number of waypoints that fall on the path."""
    rover = _make_rover(start=(0, 0))
    path: list[tuple[int, int]] = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)]
    waypoints: set[tuple[int, int]] = {(0, 2), (0, 4)}
    log = execute_path(rover, path, waypoints=waypoints)
    assert log.waypoints_reached() == 2


def test_execute_path_waypoint_not_on_path_not_counted() -> None:
    """Waypoints not on the path do not produce waypoint_reached events."""
    rover = _make_rover(start=(0, 0))
    path: list[tuple[int, int]] = [(0, 0), (0, 1), (0, 2)]
    waypoints: set[tuple[int, int]] = {(9, 9)}  # not on path
    log = execute_path(rover, path, waypoints=waypoints)
    assert log.waypoints_reached() == 0


def test_execute_path_waypoint_after_step_event() -> None:
    """waypoint_reached event follows immediately after the corresponding step event."""
    rover = _make_rover(start=(0, 0))
    path: list[tuple[int, int]] = [(0, 0), (0, 1), (0, 2)]
    waypoints: set[tuple[int, int]] = {(0, 1)}
    log = execute_path(rover, path, waypoints=waypoints)

    event_types = [e.event_type for e in log.events]
    wp_idx = event_types.index("waypoint_reached")
    assert event_types[wp_idx - 1] == "step"


# ---------------------------------------------------------------------------
# Low battery event
# ---------------------------------------------------------------------------


def test_execute_path_emits_low_battery_event() -> None:
    """execute_path emits a low_battery event when battery drops below threshold.

    Each cardinal step on 20 m resolution at 0.042 m/s with drive_draw_w=120 W
    and drive_efficiency=0.5 costs ~7.94 Wh.  A 65 Wh battery (threshold 20%
    = 13 Wh) reaches ~9.4 Wh after 7 steps — below threshold but still > 0,
    so mission_failed is not triggered and low_battery is emitted.
    """
    config = RoverConfig(
        battery_capacity_wh=65.0,
        low_battery_threshold_pct=20.0,
    )
    terrain = _make_flat_terrain()
    rover = Rover(terrain=terrain, start=(0, 0), config=config)
    # 8 cells → 7 steps; enough to cross the 20% threshold without exhausting
    path: list[tuple[int, int]] = [(0, i) for i in range(8)]
    log = execute_path(rover, path)

    event_types = [e.event_type for e in log.events]
    assert "low_battery" in event_types


def test_execute_path_low_battery_emitted_only_once() -> None:
    """low_battery event is emitted at most once per mission."""
    config = RoverConfig(battery_capacity_wh=65.0, low_battery_threshold_pct=20.0)
    terrain = _make_flat_terrain()
    rover = Rover(terrain=terrain, start=(0, 0), config=config)
    path: list[tuple[int, int]] = [(0, i) for i in range(8)]
    log = execute_path(rover, path)

    low_battery_count = sum(1 for e in log.events if e.event_type == "low_battery")
    assert low_battery_count <= 1


# ---------------------------------------------------------------------------
# Mission failed
# ---------------------------------------------------------------------------


def test_execute_path_mission_failed_on_exhausted_battery() -> None:
    """execute_path emits mission_failed and returns partial log when battery is exhausted."""
    rover = _make_rover(start=(0, 0), battery_capacity_wh=0.001)
    path: list[tuple[int, int]] = [(0, 0), (0, 1), (0, 2)]
    log = execute_path(rover, path)

    event_types = [e.event_type for e in log.events]
    assert "mission_failed" in event_types
    assert "mission_complete" not in event_types


def test_execute_path_never_raises_on_rover_failure() -> None:
    """execute_path never raises even when battery is exhausted."""
    rover = _make_rover(start=(0, 0), battery_capacity_wh=0.001)
    path: list[tuple[int, int]] = [(0, 0), (0, 1), (0, 2), (0, 3)]
    # Should not raise
    log = execute_path(rover, path)
    assert log is not None


def test_execute_path_partial_log_has_mission_start() -> None:
    """Partial log (mission_failed) still begins with mission_start."""
    rover = _make_rover(start=(0, 0), battery_capacity_wh=0.001)
    path: list[tuple[int, int]] = [(0, 0), (0, 1), (0, 2)]
    log = execute_path(rover, path)
    assert log.events[0].event_type == "mission_start"


# ---------------------------------------------------------------------------
# Single-cell path (trivial)
# ---------------------------------------------------------------------------


def test_execute_path_single_cell_path() -> None:
    """execute_path on a single-cell path returns mission_start then mission_complete."""
    rover = _make_rover(start=(3, 3))
    log = execute_path(rover, [(3, 3)])

    event_types = [e.event_type for e in log.events]
    assert event_types == ["mission_start", "mission_complete"]


def test_execute_path_single_cell_no_step_events() -> None:
    """Single-cell path produces no step events."""
    rover = _make_rover(start=(0, 0))
    log = execute_path(rover, [(0, 0)])
    assert log.distance_cells() == 0


# ---------------------------------------------------------------------------
# MissionLog statistics on engine output
# ---------------------------------------------------------------------------


def test_execute_path_distance_cells_3_cell_path() -> None:
    """distance_cells on a complete 3-cell path result equals 2."""
    rover = _make_rover(start=(0, 0))
    path: list[tuple[int, int]] = [(0, 0), (0, 1), (0, 2)]
    log = execute_path(rover, path)
    assert log.distance_cells() == 2


def test_execute_path_waypoints_reached_matches_set() -> None:
    """waypoints_reached equals the number of waypoints in the set that fall on the path."""
    rover = _make_rover(start=(0, 0))
    path: list[tuple[int, int]] = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)]
    waypoints: set[tuple[int, int]] = {(0, 1), (0, 3)}
    log = execute_path(rover, path, waypoints=waypoints)
    assert log.waypoints_reached() == 2


def test_execute_path_no_waypoints_by_default() -> None:
    """execute_path with no waypoints argument produces zero waypoint_reached events."""
    rover = _make_rover(start=(0, 0))
    log = execute_path(rover, [(0, 0), (0, 1), (0, 2)])
    assert log.waypoints_reached() == 0


def test_execute_path_empty_waypoints_set() -> None:
    """execute_path with empty waypoints set produces zero waypoint_reached events."""
    rover = _make_rover(start=(0, 0))
    log = execute_path(rover, [(0, 0), (0, 1)], waypoints=set())
    assert log.waypoints_reached() == 0


# ---------------------------------------------------------------------------
# Duration and battery stats
# ---------------------------------------------------------------------------


def test_execute_path_duration_positive_for_multi_cell() -> None:
    """Mission duration is positive for a multi-cell path."""
    rover = _make_rover(start=(0, 0))
    log = execute_path(rover, [(0, 0), (0, 1), (0, 2)])
    assert log.duration_s() > 0.0


def test_execute_path_final_battery_decreases() -> None:
    """Battery at end of mission is less than 100% after moving."""
    rover = _make_rover(start=(0, 0))
    log = execute_path(rover, [(0, 0), (0, 1), (0, 2)])
    assert log.final_battery() < 100.0


def test_execute_path_final_battery_non_negative() -> None:
    """Battery percentage is never negative at end of mission."""
    rover = _make_rover(start=(0, 0))
    log = execute_path(rover, [(0, 0), (0, 1), (0, 2)])
    assert log.final_battery() >= 0.0


# ---------------------------------------------------------------------------
# Event position matches path
# ---------------------------------------------------------------------------


def test_execute_path_step_positions_match_path() -> None:
    """Step event positions correspond to the path cells traversed."""
    rover = _make_rover(start=(0, 0))
    path: list[tuple[int, int]] = [(0, 0), (0, 1), (0, 2)]
    log = execute_path(rover, path)

    step_positions = [e.position for e in log.events if e.event_type == "step"]
    assert step_positions == [(0, 1), (0, 2)]
